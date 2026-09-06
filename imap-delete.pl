#!/usr/bin/env perl
# imap-delete.pl — locate and delete specific messages on a live IMAP
# account, given a list of target Message-IDs (e.g. from
# extract-mbox-message.pl's manifest.json). Companion tool: that script
# reads the local mbox cache; this one acts on the real mail server.
#
# Usage:
#   IMAP_USER=you@example.com IMAP_PW=secret perl imap-delete.pl \
#       <msgid-file> --sender=PATTERN <folder1> [<folder2> ...] [--delete]
#
#   <msgid-file>     one Message-ID per line, in <...> form (as they
#                    appear in the Message-Id: header)
#   --sender=PATTERN a LITERAL SUBSTRING to match against the From header
#                    via IMAP SEARCH FROM — this is NOT a regex. IMAP
#                    SEARCH FROM does substring matching against the raw
#                    header text (display name + address), so:
#                      - "chatgpt" won't match a sender whose From reads
#                        "OpenAI" <...> — you may need two passes with
#                        different substrings for a platform that sends
#                        under multiple display names/domains
#                      - "cozyinkc" won't match "Cozy In KC" <platform@
#                        hostfully.com> — a spaced display name needs the
#                        spaced substring ("Cozy"), not the no-space
#                        domain form
#                    When in doubt, use the shortest distinctive substring
#                    (a brand name) rather than a domain, and re-run with
#                    a second pattern if the matched count looks low.
#   <folder...>      candidate folders to search, e.g. INBOX, Archive,
#                    Spam, Sent, Drafts, and any Folders/<alias> your
#                    account files mail into (run a LIST command first if
#                    unsure what folders exist)
#   --delete         without this flag, the script only reports where
#                    each target Message-ID currently lives (read-only,
#                    safe to run first). With it, matched messages get
#                    COPY'd to Trash, flagged \Deleted in their source
#                    folder, then that source folder is EXPUNGEd.
#
# ⚠️ NEVER include "Trash" in the folder list — either for search or
# delete. If a target message is already in Trash, that's the terminal
# state already; searching/expunging Trash risks permanently purging
# OTHER messages that happen to be sitting there with a dormant \Deleted
# flag (confirmed to actually happen once — see project memory
# project_thunderbird_live_imap_delete.md for the incident). Messages not
# found in any folder you passed are very likely already in Trash —
# that's fine, no action needed on them.
#
# Connection: defaults to Proton Bridge on localhost (127.0.0.1:1143,
# STARTTLS) — override with IMAP_HOST / IMAP_PORT env vars for a
# different IMAP server. TLS cert verification is disabled
# (SSL_VERIFY_NONE) since this targets a loopback bridge with a
# self-signed cert; tighten this if pointing at a real remote server.
#
# Safe to re-run: locate (no --delete) is fully read-only. Delete is
# idempotent per message — already-deleted targets just report "not
# found" on a second pass.

use strict; use warnings;
use IO::Socket::INET; use IO::Socket::SSL;

my $user = $ENV{IMAP_USER} or die "set IMAP_USER\n";
my $pass = $ENV{IMAP_PW} or die "set IMAP_PW\n";
my $host = $ENV{IMAP_HOST} || '127.0.0.1';
my $port = $ENV{IMAP_PORT} || 1143;

my @args = @ARGV;
my $msgid_file = shift @args or die "usage: $0 <msgid-file> --sender=PATTERN <folder...> [--delete]\n";
my $do_delete = 0;
my $sender_pattern;
my @folders;
for my $a (@args) {
    if ($a eq '--delete') { $do_delete = 1; }
    elsif ($a =~ /^--sender=(.+)$/) { $sender_pattern = $1; }
    else { push @folders, $a; }
}
die "must pass --sender=PATTERN\n" unless $sender_pattern;
if (grep { lc($_) eq 'trash' } @folders) {
    die "Refusing to run: 'Trash' must not be in the folder list (see header comment for why).\n";
}

open(my $mf, '<', $msgid_file) or die "can't open $msgid_file: $!\n";
my @targets = <$mf>;
chomp @targets;
close $mf;
my %want = map { $_ => 1 } @targets;
print "Loaded ", scalar(@targets), " target Message-IDs.\n";

my $tag=0; sub nt { sprintf("a%03d", ++$tag) }
sub send_cmd { my ($s,$c)=@_; print $s "$c\r\n"; }
sub read_until { my ($s,$t)=@_; my @l; while(my $line=<$s>){ $line=~s/\r?\n$//; push @l,$line; return @l if $line=~/^\Q$t\E\s+(OK|NO|BAD)/i; } die "closed\n"; }

my $sock = IO::Socket::INET->new(PeerAddr=>$host,PeerPort=>$port,Proto=>'tcp',Timeout=>20) or die "$@\n";
<$sock>;
my $t=nt(); send_cmd($sock,"$t STARTTLS"); read_until($sock,$t);
IO::Socket::SSL->start_SSL($sock, SSL_verify_mode=>IO::Socket::SSL::SSL_VERIFY_NONE()) or die "$!\n";
$t=nt(); send_cmd($sock,"$t LOGIN \"$user\" \"$pass\""); my @r=read_until($sock,$t);
die "login failed\n" unless $r[-1]=~/OK/i;
undef $pass;

my %by_folder;
my %found;

for my $folder (@folders) {
    $t=nt(); send_cmd($sock,"$t SELECT \"$folder\""); @r=read_until($sock,$t);
    unless ($r[-1]=~/OK/i) { print "SELECT $folder: SKIP ($r[-1])\n"; next; }

    $t=nt(); send_cmd($sock,"$t UID SEARCH FROM \"$sender_pattern\""); @r=read_until($sock,$t);
    my @uids;
    for my $line (@r) { if ($line=~/^\*\s+SEARCH\s+(.+)$/){ @uids=split(/\s+/,$1);} }
    print "Folder $folder: ", scalar(@uids), " candidate UIDs\n";
    next unless @uids;

    my $uidset = join(',', @uids);
    $t=nt(); send_cmd($sock,"$t UID FETCH $uidset (UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"); @r=read_until($sock,$t);
    my $cur_uid;
    for my $line (@r) {
        if ($line =~ /UID\s+(\d+)/) { $cur_uid = $1; }
        if ($line =~ /Message-Id:\s*(<[^>]+>)/i) {
            my $mid = $1;
            if ($want{$mid} && !$found{$mid}) {
                $found{$mid} = "$folder:$cur_uid";
                push @{$by_folder{$folder}}, $cur_uid;
            }
        }
    }
}

print "\n--- Locate summary ---\n";
print "Matched: ", scalar(keys %found), " / ", scalar(@targets), "\n";
for my $folder (sort keys %by_folder) {
    print "  $folder: ", scalar(@{$by_folder{$folder}}), " message(s)\n";
}
my @missing = grep { !$found{$_} } @targets;
if (@missing) {
    print "NOT found in any listed folder (", scalar(@missing), ") — likely already in Trash:\n";
    print "  $_\n" for @missing;
}

if ($do_delete) {
    print "\n--- Deleting ---\n";
    for my $folder (sort keys %by_folder) {
        my @uids = @{$by_folder{$folder}};
        my $uidset = join(',', @uids);
        print "=== $folder (", scalar(@uids), " messages) ===\n";
        $t=nt(); send_cmd($sock,"$t SELECT \"$folder\""); @r=read_until($sock,$t);
        die "select failed for $folder, aborting\n" unless $r[-1]=~/OK/i;

        $t=nt(); send_cmd($sock,"$t UID COPY $uidset \"Trash\""); @r=read_until($sock,$t);
        print "  COPY to Trash: $r[-1]\n";
        if ($r[-1] !~ /OK/i) { print "  COPY FAILED — skipping $folder\n"; next; }

        $t=nt(); send_cmd($sock,"$t UID STORE $uidset +FLAGS (\\Deleted)"); @r=read_until($sock,$t);
        print "  STORE \\Deleted: $r[-1]\n";
        if ($r[-1] !~ /OK/i) { print "  STORE FAILED — aborting expunge for $folder\n"; next; }

        $t=nt(); send_cmd($sock,"$t EXPUNGE"); @r=read_until($sock,$t);
        print "  EXPUNGE: $r[-1]\n";
    }
    print "\nBATCH DELETE DONE.\n";
}

$t=nt(); send_cmd($sock,"$t LOGOUT"); read_until($sock,$t);

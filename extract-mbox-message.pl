#!/usr/bin/env perl
# extract-mbox-message.pl — pull message(s) out of a Thunderbird/mbox file.
#
# Two modes:
#
# 1. Substring mode (original behavior, unchanged):
#      perl extract-mbox-message.pl <mboxfile> <needle>
#    Matches a plain substring anywhere in the raw message (headers or
#    body) and prints each match as raw RFC822 text, delimited by
#    =====MSGSTART=====/=====MSGEND===== markers, so a caller can carve
#    out individual messages (e.g. with sed) and re-save them as
#    standalone .eml files, or pipe them into another parser.
#
#    Example — find a message by a unique Date header string and save it:
#      perl extract-mbox-message.pl "INBOX" "Wed, 12 Aug 2026 17:50:01 +0000" \
#        | sed -n '/^=====MSGSTART=====$/,/^=====MSGEND=====$/p' \
#        | sed '1d;$d' > "message.eml"
#
# 2. Structured extraction mode (--out-dir): a single streaming pass that
#    matches messages against one or more Subject regexes (optionally
#    narrowed by a From regex), then for each match writes:
#      <out-dir>/raw-eml/NNN-<slug>.eml        — unmodified original message
#      <out-dir>/decoded/NNN-<slug>.html|.txt  — quoted-printable/base64
#                                                 decoded body, for reading
#      <out-dir>/attachments/NNN-<slug>--<filename>.pdf
#                                               — any base64 PDF parts,
#                                                 extracted intact
#      <out-dir>/manifest.json                 — index: subject/from/to/date
#                                                 per matched file
#    Subject/From headers are RFC2047-decoded (=?utf-8?q?...?=) before
#    matching and before being recorded, so encoded-word subjects match
#    correctly.
#
#    Usage:
#      perl extract-mbox-message.pl <mboxfile> --out-dir=<dir> \
#        [--from=REGEX] --subject=REGEX [--subject=REGEX ...]
#
#    --subject may be repeated to pull several different message types out
#    of the same mbox in one pass — streaming a multi-GB mbox once instead
#    of once per target is the whole point of this mode.
#
#    Example — pull a support-ticket thread and two dispute-letter emails,
#    only from a specific sender, in one pass:
#      perl extract-mbox-message.pl "All Mail" --out-dir=evidence \
#        --from='support@example\.com' \
#        --subject='ticket #12345' \
#        --subject='re:\s*12345'
#
# Notes:
# - mbox messages are delimited by lines starting "From - <date>"; this
#   script streams the file and buffers between those delimiters rather
#   than loading the whole file into memory (mbox files here run 100MB-2GB+).
# - In substring mode, matching is a plain substring search (index), not a
#   regex, so special regex characters in the needle don't need escaping.
# - In structured mode, --subject/--from are Perl regexes (case-insensitive),
#   matched against the RFC2047-decoded header value.
# - Thunderbird's Date: header is UTC, not local time — a message sent late
#   evening Eastern can be timestamped the next calendar day in UTC. Pad
#   date-range searches accordingly rather than exact-matching one date.

use strict;
use warnings;
use MIME::Base64 qw(decode_base64);
use MIME::QuotedPrint qw(decode_qp);
use Encode qw(decode);
use Encode::MIME::Header;
use File::Path qw(make_path);
use JSON::PP qw(encode_json);

my @args = @ARGV;
my $file = shift @args;
die "usage: $0 <mboxfile> <needle>\n" .
    "       $0 <mboxfile> --out-dir=<dir> [--from=REGEX] --subject=REGEX [--subject=REGEX ...]\n"
    unless defined $file;

my ($out_dir, $from_re, @subject_res);
my @plain_args;
for my $a (@args) {
    if ($a =~ /^--out-dir=(.+)$/)  { $out_dir = $1; }
    elsif ($a =~ /^--from=(.+)$/)  { $from_re = $1; }
    elsif ($a =~ /^--subject=(.+)$/) { push @subject_res, $1; }
    else { push @plain_args, $a; }
}

if (defined $out_dir) {
    die "structured mode needs at least one --subject=REGEX\n" unless @subject_res;
    run_structured($file, $out_dir, $from_re, \@subject_res);
} else {
    my $needle = $plain_args[0];
    die "usage: $0 <mboxfile> <needle>\n" unless defined $needle;
    run_substring($file, $needle);
}

# ---------------------------------------------------------------------------
# Mode 1: original substring search, unchanged behavior.
# ---------------------------------------------------------------------------
sub run_substring {
    my ($file, $needle) = @_;
    open(my $fh, '<:raw', $file) or die "can't open $file: $!";

    my ($cur_from_line, $cur_body) = (undef, '');
    my @out;

    while (my $line = <$fh>) {
        if ($line =~ /^From - /) {
            if (defined $cur_from_line && index($cur_body, $needle) >= 0) {
                push @out, $cur_body;
            }
            $cur_from_line = $line;
            $cur_body = '';
        } else {
            $cur_body .= $line;
        }
    }
    if (defined $cur_from_line && index($cur_body, $needle) >= 0) {
        push @out, $cur_body;
    }
    close($fh);

    print "FOUND: " . scalar(@out) . " messages\n";
    for my $m (@out) {
        print "=====MSGSTART=====\n$m\n=====MSGEND=====\n";
    }
}

# ---------------------------------------------------------------------------
# Mode 2: structured extraction — subject/from match, decode, attachments.
# ---------------------------------------------------------------------------
sub run_structured {
    my ($file, $out_dir, $from_re, $subject_res) = @_;

    make_path("$out_dir/raw-eml", "$out_dir/decoded", "$out_dir/attachments");

    open(my $fh, '<:raw', $file) or die "can't open $file: $!";

    my @header_lines;
    my @body_lines;
    my $in_headers = 0;
    my $n = 0;
    my @manifest;

    my $flush = sub {
        return unless @header_lines;
        my %h;
        my $cur_key;
        for my $line (@header_lines) {
            if ($line =~ /^([A-Za-z-]+):\s?(.*)$/) {
                $cur_key = lc($1);
                $h{$cur_key} = defined($h{$cur_key}) ? "$h{$cur_key} $2" : $2;
            } elsif (defined $cur_key && $line =~ /^\s/) {
                my $t = $line;
                $t =~ s/^\s+|\s+$//g;
                $h{$cur_key} .= " $t";
            }
        }
        # Source lines are mixed CRLF/LF depending on which relay hop wrote
        # them, so strip a stray trailing \r from every folded header value
        # before it's matched against or recorded (Perl's `$` only excludes
        # a trailing \n, not a trailing \r).
        $_ =~ s/\r$// for values %h;

        for my $k (qw(subject from)) {
            next unless defined $h{$k};
            $h{$k} = eval { decode('MIME-Header', $h{$k}) } // $h{$k};
        }

        return unless defined $h{subject};
        return if defined $from_re && (!defined $h{from} || $h{from} !~ /$from_re/i);
        my $matched = 0;
        for my $re (@$subject_res) {
            if ($h{subject} =~ /$re/i) { $matched = 1; last; }
        }
        return unless $matched;

        $n++;
        my $slug = lc($h{subject});
        $slug =~ s/[^a-z0-9]+/-/g;
        $slug = substr($slug, 0, 60);
        $slug =~ s/^-+|-+$//g;
        my $base = sprintf("%03d-%s", $n, $slug || 'no-subject');

        my $body = join('', @body_lines);
        open(my $eml, '>:raw', "$out_dir/raw-eml/$base.eml") or die $!;
        print $eml join('', @header_lines) . "\n" . $body;
        close($eml);

        my $ct = $h{'content-type'} // '';
        my ($boundary) = $ct =~ /boundary=(?:")?([^;"\r\n]+)/i;
        my $decoded_text;
        my @pdf_files;

        if (defined $boundary) {
            my $qb = quotemeta($boundary);
            my @parts = split(/--$qb(?:--)?\r?\n/, $body);
            for my $part (@parts) {
                next unless $part =~ /\S/;
                my ($phdr, $pbody) = split(/\r?\n\r?\n/, $part, 2);
                $pbody //= '';
                my ($pct)  = $phdr =~ /Content-Type:\s*([^\r\n;]+)/i;
                my ($pcte) = $phdr =~ /Content-Transfer-Encoding:\s*([^\r\n;]+)/i;
                my ($pfn)  = $phdr =~ /filename="?([^"\r\n;]+)"?/i;
                $pct  = lc($pct  // '');
                $pcte = lc($pcte // '');
                $pct  =~ s/^\s+|\s+$//g;
                $pcte =~ s/^\s+|\s+$//g;

                if ($pct eq 'application/pdf' && $pcte eq 'base64') {
                    (my $clean = $pbody) =~ s/[^A-Za-z0-9+\/=]//g;
                    my $bin = decode_base64($clean);
                    my $fname = $pfn // "$base.pdf";
                    my $path = "$out_dir/attachments/$base--$fname";
                    open(my $pf, '>:raw', $path) or die $!;
                    print $pf $bin;
                    close($pf);
                    push @pdf_files, $fname;
                } elsif ($pct eq 'text/html' && !defined $decoded_text) {
                    $decoded_text = $pcte eq 'base64'
                        ? do { (my $c = $pbody) =~ s/[^A-Za-z0-9+\/=]//g; decode_base64($c); }
                        : decode_qp($pbody);
                } elsif ($pct =~ m{^text/} && !defined $decoded_text) {
                    $decoded_text = decode_qp($pbody);
                }
            }
        } elsif (($h{'content-transfer-encoding'} // '') =~ /quoted-printable/i) {
            $decoded_text = decode_qp($body);
        } else {
            $decoded_text = $body;
        }

        if (defined $decoded_text) {
            my $ext = ($ct =~ m{text/html}i) ? 'html' : 'txt';
            open(my $df, '>:raw', "$out_dir/decoded/$base.$ext") or die $!;
            print $df $decoded_text;
            close($df);
        }

        push @manifest, {
            file => $base,
            subject => $h{subject},
            from => $h{from},
            to => $h{to},
            date => $h{date},
            pdfAttachments => \@pdf_files,
        };
    };

    while (my $line = <$fh>) {
        if ($line =~ /^From - /) {
            $flush->();
            @header_lines = ();
            @body_lines = ();
            $in_headers = 1;
            next;
        }
        if ($in_headers) {
            if ($line =~ /^\r?\n$/) { $in_headers = 0; next; }
            push @header_lines, $line;
        } else {
            push @body_lines, $line;
        }
    }
    $flush->();
    close($fh);

    open(my $mf, '>:encoding(UTF-8)', "$out_dir/manifest.json") or die $!;
    print $mf encode_json(\@manifest);
    close($mf);

    print "Matched $n message(s) into $out_dir/\n";
}

#!/usr/bin/env perl
# extract-mbox-message.pl — pull full message(s) out of a Thunderbird/mbox
# file by matching a plain substring ("needle") anywhere in the raw message
# (headers or body). Prints each match as raw RFC822 text, delimited by
# =====MSGSTART=====/=====MSGEND===== markers, so a caller can carve out
# individual messages (e.g. with sed) and re-save them as standalone .eml
# files, or pipe them into another parser.
#
# Usage:
#   perl extract-mbox-message.pl <mboxfile> <needle>
#
# Example — find a message by a unique Date header string and save it:
#   perl extract-mbox-message.pl "INBOX" "Wed, 12 Aug 2026 17:50:01 +0000" \
#     | sed -n '/^=====MSGSTART=====$/,/^=====MSGEND=====$/p' \
#     | sed '1d;$d' > "message.eml"
#
# Notes:
# - mbox messages are delimited by lines starting "From - <date>"; this
#   script streams the file and buffers between those delimiters rather
#   than loading the whole file into memory (mbox files here run 100MB-2GB+).
# - Matching is a plain substring search (index), not a regex, so special
#   regex characters in the needle don't need escaping.
# - Thunderbird's Date: header is UTC, not local time — a message sent late
#   evening Eastern can be timestamped the next calendar day in UTC. Pad
#   date-range searches accordingly rather than exact-matching one date.

use strict;
use warnings;

my ($file, $needle) = @ARGV;
die "usage: $0 <mboxfile> <needle>\n" unless defined $file && defined $needle;

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

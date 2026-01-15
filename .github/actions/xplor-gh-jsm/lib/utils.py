import argparse
import shlex
from datetime import timedelta


def compact_str(string):
    """Compact a string by removing leading and trailing whitespace."""
    return ''.join(char.lower() for char in string.lower() if char.isalnum()) if isinstance(string, str) else string


def compact_list_contains(string_list, string):
    """Check if a compacted string is in a list of compacted strings."""
    return compact_str(string) in [compact_str(s) for s in string_list]


def now_in_utc(delta=None):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if isinstance(delta, timedelta):
        now = now + delta
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0000"


def str_to_bool(value):
    """Convert string to boolean."""
    true_values = ['true', 't', '1', 'yes', 'y']
    false_values = ['false', 'f', '0', 'no', 'n']

    if isinstance(value, bool):
        return value
    if value.lower() in true_values:
        return True
    if value.lower() in false_values:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: '{value}'")


def parse_proof_of_success_url_line(line):
    try:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument('-H', '--header', action='append', help='Header values', default=[])
        parser.add_argument('url', help='The URL')
        parsed_args = parser.parse_args(shlex.split(line))
        headers_dict = {'Cache-Control': 'no-cache'}
        for header in parsed_args.header:
            key, value = header.split(':', 1)
            headers_dict[key.strip()] = value.strip()
        return parsed_args.url, headers_dict
    except SystemExit:
        print("Error: Invalid input format on PROOF_OF_SUCCESS. Usage (per line): [-H \"key: value\"]... url\n"
              "Examples:\n"
              "  https://example.com/proof.json\n"
              "  -H \"Authorization: Bearer token_value\" https://example.com/proof.json")
        exit(1)

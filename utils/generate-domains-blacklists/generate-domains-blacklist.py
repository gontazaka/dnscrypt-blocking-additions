#! /usr/bin/env python

# run with python generate-domains-blacklist.py

import argparse
import re
import sys
import urllib.request, urllib.error
import chardet

#===== configuration ====>
class Configuration:
	USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit Chrome Safari'
#<==== configuration =====

def parse_list(content, trusted=False):
    rx_comment = re.compile(r'^(#|$)')
    rx_inline_comment = re.compile(r'\s*#\s*[a-z0-9-].*$')
    rx_u = re.compile(r'^@*\|\|([a-z0-9.-]+[.][a-z]{2,})\^?(\$(popup|third-party))?$')
    rx_l = re.compile(r'^([a-z0-9.-]+[.][a-z]{2,})$')
    rx_h = re.compile(r'^[0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3}\s+([a-z0-9.-]+[.][a-z]{2,})$')
    rx_mdl = re.compile(r'^"[^"]+","([a-z0-9.-]+[.][a-z]{2,})",')
    rx_b = re.compile(r'^([a-z0-9.-]+[.][a-z]{2,}),.+,[0-9: /-]+,')
    rx_dq = re.compile(r'^address=/([a-z0-9.-]+[.][a-z]{2,})/.')
    rx_trusted = re.compile(r'^(=?[*a-z0-9.-]+)$')

    names = set()
    rx_set = [rx_u, rx_l, rx_h, rx_mdl, rx_b, rx_dq]
    if trusted:
        rx_set = [rx_trusted]
    for line in content.splitlines():
        line = str.lower(str.strip(line))
        if rx_comment.match(line):
            continue
        line = rx_inline_comment.sub('', line)
        for rx in rx_set:
            matches = rx.match(line)
            if not matches:
                continue
            name = matches.group(1)
            names.add(name)
    return names


def load_from_url(url):
    sys.stderr.write("Loading data from [{}]\n".format(url))
    # Some lists seem to intentionally 404 the default user-agent...
    # Taken from https://techblog.willshouse.com/2012/01/03/most-common-user-agents/
    headers = {
        'user-agent': Configuration.USER_AGENT
    }
    req = urllib.request.Request(url=url, method='GET',headers=headers)

    trusted = False
    if req.type == "file":
        trusted = True
    
    response = None
    try:
        response = urllib.request.urlopen(req, timeout=int(args.timeout))
    except urllib.error.URLError as err:
        raise Exception("[{}] could not be loaded: {}\n".format(url, err))
    except urllib.error.ContentTooShortError as err:
        raise Exception("[{}] data is less than the expected amount: {}\n".format(url, err))
    
    if trusted is False and response.getcode() != 200:
        raise Exception("[{}] returned HTTP code {}\n".format(url, response.getcode()))
    
    content = response.read()
    detres = chardet.detect(content)
    decoded_content = content.decode(detres['encoding'])

    return (decoded_content, trusted)


def name_cmp(name):
    parts = name.split(".")
    parts.reverse()
    return str.join(".", parts)


def has_suffix(names, name):
    parts = str.split(name, ".")
    while parts:
        parts = parts[1:]
        if str.join(".", parts) in names:
            return True

    return False


def whitelist_from_url(url):
    if not url:
        return set()
    content, trusted = load_from_url(url)

    return parse_list(content, trusted)


def domainlist_from_config_file(conf, outfile, whitelist, time_restricted_url, ignore_retrieval_failure):
    blacklists = {}
    whitelisted_names = set()
    all_names = set()
    unique_names = set()

    # Load conf & blacklists
    with open(conf, encoding='utf_8_sig') as fd:
        for line in fd:
            line = str.strip(line)
            if str.startswith(line, "#") or line == "":
                continue
            url = line
            try:
                content, trusted = load_from_url(url)
                names = parse_list(content, trusted)
                blacklists[url] = names
                all_names |= names
            except Exception as e:
                sys.stderr.write(e.message)
                if not ignore_retrieval_failure:
                    exit(1)

    # Time-based blacklist
    if time_restricted_url and not re.match(r'^[a-z0-9]+:', time_restricted_url):
        time_restricted_url = "file:" + time_restricted_url

    if time_restricted_url:
        time_restricted_content, trusted = load_from_url(time_restricted_url)
        time_restricted_names = parse_list(time_restricted_content)

        if time_restricted_names:
            outfile.write("########## Time-based blacklist ##########\n")
            for name in time_restricted_names:
                outfile.write(name)

        # Time restricted names should be whitelisted, or they could be always blocked
        whitelisted_names |= time_restricted_names

    # Whitelist
    if whitelist and not re.match(r'^[a-z0-9]+:', whitelist):
        whitelist = "file:" + whitelist

    whitelisted_names |= whitelist_from_url(whitelist)

    # Process blacklists
    for url, names in blacklists.items():
        outfile.write("\n\n########## Blacklist from {} ##########\n".format(url))
        ignored, whitelisted = 0, 0
        list_names = list()
        for name in names:
            if has_suffix(all_names, name) or name in unique_names:
                ignored = ignored + 1
            elif has_suffix(whitelisted_names, name) or name in whitelisted_names:
                whitelisted = whitelisted + 1
            else:
                list_names.append(name)
                unique_names.add(name)

        list_names.sort(key=name_cmp)
        if ignored:
            outfile.write("# Ignored duplicates: {}\n".format(ignored))
        if whitelisted:
            outfile.write("# Ignored entries due to the whitelist: {}\n".format(whitelisted))
        for name in list_names:
            outfile.write("{}\n".format(name))


argp = argparse.ArgumentParser(description="Create a unified blacklist from a set of local and remote files")
argp.add_argument("-c", "--config", default="domains-blacklist.conf",
    help="file containing blacklist sources")
argp.add_argument("-w", "--whitelist", default="domains-whitelist.conf",
    help="file containing a set of names to exclude from the blacklist")
argp.add_argument("-r", "--time-restricted", default="domains-time-restricted.txt",
    help="file containing a set of names to be time restricted")
argp.add_argument("-i", "--ignore-retrieval-failure", action='store_true',
    help="generate list even if some urls couldn't be retrieved")
argp.add_argument("-t", "--timeout", default=30,
    help="URL open timeout")
argp.add_argument("-o", "--output", default="",
    help="file output")
args = argp.parse_args()

time_restricted = args.time_restricted
ignore_retrieval_failure = args.ignore_retrieval_failure

wdf = open('whitelist-domains.txt', 'w', encoding='utf_8', newline='\n')
domainlist_from_config_file(args.whitelist, wdf, None, time_restricted, ignore_retrieval_failure)
wdf.close()

blf = open(args.output if args.output else 'blacklist.txt', 'w', encoding='utf_8', newline='\n')
domainlist_from_config_file(args.config, blf, "whitelist-domains.txt", time_restricted, ignore_retrieval_failure)
blf.close()

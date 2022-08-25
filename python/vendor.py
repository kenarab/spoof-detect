#!/usr/bin/env python3
import csv
import concurrent.futures
import requests

from progress.bar import ChargingBar

from entity import Entity
from common import defaults,mkdir
import screenshot
import web

def query_vendor_site(e: Entity):
    page = web.get_page(e)
    fn = web.get_cert(e)
    lfn = web.get_logos(e, page)
    screenshot.sc_entity(e)
    return (fn, lfn)

def from_csv(fn):
    with open(fn, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        with concurrent.futures.ThreadPoolExecutor(max_workers = 5) as executor:
            futures = {executor.submit(query_vendor_site, e): e for e in [Entity.from_dict(d) for d in reader]}
            bar = ChargingBar('Processing', max=len(futures))
            for f in concurrent.futures.as_completed(futures):
                url = futures[f]
                try:
                    (cert, logos) = f.result()
                except Exception as exc:
                    print('%r generated an exception: %s' % (url, exc))
                    raise
                else:
                    print(cert, logos)
                bar.next()
            bar.finish()

#query_vendor_site(Entity.from_dict({'url':'http://www.bancoprovincia.com.ar', 'bco':'debug'}))
#exit()

if __name__ == '__main__':
    from_csv(defaults.MAIN_CSV_PATH)

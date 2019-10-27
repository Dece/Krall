import argparse
import os
import pathlib
import re
from urllib.parse import urljoin, urlparse
import sys

from bs4 import BeautifulSoup
import requests
import superslug
from tenacity import retry, stop_after_attempt, wait_fixed


IMAGE_PROVIDERS = [
    'imgur.com',
    'servimg.com',
]

IMAGE_RE = re.compile(
    r'src=\"(https?://.*?(' +
    '|'.join(IMAGE_PROVIDERS).replace('.', r'\.') +
    r').*?)\"'
)


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument('url', type=str)
    argparser.add_argument('-o', '--output', type=str, default='.',
                           help='Output folder')
    args = argparser.parse_args()

    process_thread(args.url, pathlib.Path(args.output))

def process_thread(url, output_dir: pathlib.Path):
    soup = get_page_soup(url)
    if soup is None:
        return

    if not output_dir.is_dir():
        output_dir.mkdir()
    title = soup.find(class_='topic-title').get_text()
    title = superslug.slugify(title)
    thread_dir = output_dir / title

    process_page(url, thread_dir, 1, soup=soup)

def process_page(url, thread_dir, page, soup=None):
    print("Processing {}...".format(url))

    if soup is None:
        soup = get_page_soup(url)
        if soup is None:
            return

    if not thread_dir.is_dir():
        thread_dir.mkdir()
    page_dir = thread_dir / str(page)
    if not page_dir.is_dir():
        page_dir.mkdir()

    # Download interesting content.
    for post in soup.find_all(class_='post'):
        content = post.find(class_='post-body-content')
        matches = IMAGE_RE.findall(str(content))
        urls = (groups[0] for groups in matches)
        urls = (url for url in urls if url is not None)
        download_urls(urls, page_dir)
    
    # Find next page.
    pagination = soup.find('ul', class_='pagination')
    next_element = pagination.find('li', class_='pagination-next')
    if next_element is None:
        return

    next_url_path = next_element.a['href'].lstrip('./')
    parsed = urlparse(url)
    next_url = "{}://{}/{}".format(parsed.scheme, parsed.netloc, next_url_path)
    process_page(next_url, thread_dir, page + 1)

@retry(wait=wait_fixed(10), stop=stop_after_attempt(5))
def get_page_soup(url):
    response = requests.get(url)
    if response.status_code != 200:
        print('Invalid status code {} for page {}'.format(
            response.status_code, url))
        return None
    
    return BeautifulSoup(response.text, 'html.parser')

def download_urls(urls, output_dir):
    for url in urls:
        download_url(url, output_dir)

@retry(wait=wait_fixed(10), stop=stop_after_attempt(5))
def download_url(url, output_dir):
    response = requests.get(url)
    if response.status_code != 200:
        print('Could not get file @ {}'.format(url))
        return

    filename = os.path.basename(urlparse(url).path)
    filepath = output_dir / filename
    with open(filepath, 'wb') as fd:
        for chunk in response.iter_content(chunk_size=128):
            fd.write(chunk)
    print('Downloaded {}'.format(filepath))

if __name__ == '__main__':
    main()

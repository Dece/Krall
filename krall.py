import argparse
import getpass
import logging
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

USERNAME = None
PASSWORD = None
SESH = None
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/60.0'


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument('url', type=str)
    argparser.add_argument('-o', '--output', type=str, default='.',
                           help='Output folder')
    argparser.add_argument('-v', '--verbose', action='store_true',
                           help='Verbose output')
    args = argparser.parse_args()

    if args.verbose:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    process_thread(args.url, pathlib.Path(args.output))

def process_thread(url, output_dir: pathlib.Path):
    soup = get_page_soup(url)
    if soup is None:
        return

    soup = check_for_login(url, soup)

    if not output_dir.is_dir():
        output_dir.mkdir()

    title = soup.find(class_='topic-title').get_text()
    title = superslug.slugify(title)
    thread_dir = output_dir / title

    process_page(url, thread_dir, 1, soup=soup)

def process_page(url, thread_dir, page, soup=None):
    print('Processing {}...'.format(url))

    if soup is None:
        soup = get_page_soup(url)
        if soup is None:
            return

    soup = check_for_login(url, soup)

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
    next_url = get_host(url) + '/' + next_url_path
    process_page(next_url, thread_dir, page + 1)

@retry(wait=wait_fixed(10), stop=stop_after_attempt(3))
def get_page_soup(url):
    response = (SESH or requests).get(url)
    response.raise_for_status()

    return BeautifulSoup(response.text, 'html.parser')

def check_for_login(url, soup):
    """ Check for the login form in soup; log in at URL if found. """
    login_form = soup.find('form', id='login')
    if login_form is None:
        # Nothing to do.
        return soup

    result = login(url, login_form)
    if result is None:
        return soup
    global SESH
    SESH, soup = result
    return soup

def download_urls(urls, output_dir):
    for url in urls:
        download_url(url, output_dir)

@retry(wait=wait_fixed(10), stop=stop_after_attempt(3))
def download_url(url, output_dir):
    response = (SESH or requests).get(url)
    response.raise_for_status()

    filename = os.path.basename(urlparse(url).path)
    filepath = output_dir / filename
    with open(filepath, 'wb') as fd:
        for chunk in response.iter_content(chunk_size=128):
            fd.write(chunk)
    print('Downloaded {}'.format(filepath))

def get_host(url):
    """ Return host with scheme from parsed URL. """
    parsed = urlparse(url)
    return '{}://{}'.format(parsed.scheme, parsed.netloc)

def login(url, form):
    login_redirect = form['action'].lstrip('./')
    login_url = get_host(url) + '/' + login_redirect

    global USERNAME, PASSWORD
    if USERNAME is None or PASSWORD is None:
        print('This page requires an account with sufficient access.')
        print('Enter your credentials (scheme is "{}")'.format(url.split('://')[0]))
        USERNAME = input('Username: ')
        PASSWORD = getpass.getpass()

    headers = {'User-Agent': USER_AGENT}
    payload = {
        'username': USERNAME,
        'password': PASSWORD,
        'redirect': form.find('input', attrs={'name': 'redirect'})['value'],
        'sid': form.find('input', attrs={'name': 'sid'})['value'],
        'login': form.find('input', attrs={'name': 'login'})['value'],
    }

    sesh = requests.Session()
    response = sesh.post(login_url, headers=headers, data=payload)

    # Always returns 200. Check if the login form is not there anymore to call
    # it a success.
    response_soup = BeautifulSoup(response.text, 'html.parser')
    if response_soup.find('form', id='login') is None:
        logging.debug('Logged in.')
        return sesh, response_soup

    logging.error('Could not log in.')
    return None


if __name__ == '__main__':
    main()

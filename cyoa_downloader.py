import sys
import os
import requests
import re
import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, urlunparse,unquote
from typing import Optional, List, Tuple
import mimetypes
import base64
import tempfile
import os
import uuid
import zipfile  
import shutil
from datetime import datetime
import argparse
import tldextract
import time

# Set up logging
logger = logging.getLogger("cyoa_downloader")
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)
wait_time = 60

def main() -> None:
    global wait_time
    parser = argparse.ArgumentParser(description="Download and process a CYOA project from a given URL. External images will be eiter added to the zip file or embedded to the project. Downloaded files can be viewed for example by using ICC plus: https://hikawasisters.neocities.org/ICCPlus/")

    parser.add_argument("url", help="The URL of the project to download.")
    parser.add_argument("filename", nargs="?", default="", help="Optional output filename.")
    parser.add_argument("-z", "--zip", action="store_true", help="Zip the output folder.")
    parser.add_argument("-b", "--both", action="store_true", help="Create both embedded json and zip file")
    parser.add_argument("-w",'--wait-time', type=int, default=60,help='Wait time in seconds before retrying after a 429 response (default: 60)' )
    args = parser.parse_args()

    wait_time = args.wait_time

    args = parser.parse_args()

    url = args.url
    file_name = args.filename
    zip_output = args.zip
    both_output = args.both

    logger.info(f"URL: {url}")
    logger.info(f"Filename: {file_name if file_name else '[auto-generated]'}")
    logger.info(f"Zip output enabled: {'Yes' if zip_output else 'No'}")
    logger.info(f"Both outputs enabled: {'Yes' if both_output else 'No'}")

    
    if zip_output:
        embed_images = False
    else:
        embed_images = True

    if both_output:
        zip_output = True
        embed_images = True

    project_source, project_url = get_project_source(url)
    if not project_source:
        logger.error("Could not find project.json")
        sys.exit(1)

    cleaned_project_source = extract_json_like_block(project_source)


    if not file_name:
        file_name = clean_url_path_component(get_first_folder_from_url(project_url) )

    if not file_name:
        file_name = clean_url_path_component(get_first_subdomain(project_url))
        
    if not file_name:
        file_name = "downloaded_cyoa"

    base_url = strip_document_from_url(project_url)

    temp_path = None
    if zip_output:
        temp_path = create_random_temp_folder()

    embed_result, download_result = process_images(cleaned_project_source,base_url,embed=embed_images,download=zip_output,temp_folder=temp_path, wait_time=20)

    if embed_images or both_output:
        logger.info(f"Saving file: {file_name+'.json'}")
        save_string_to_file(embed_result, file_name+'.json')
    if both_output or not embed_images:
        save_string_to_file(download_result,'project.json',temp_path)
        logger.info(f"Saving file: {file_name+'.zip'}")
        zip_temp_folder(temp_path, zip_name=file_name+'.zip')
        delete_temp_folder(temp_path)

    logger.info("Download successful.")


def get_project_source(url: str, depth: int = 0) -> Tuple[Optional[str], str]:
    if depth > 3:
        logger.warning(f"Max recursion depth reached at {url}")
        return None, ""
    
    if 'cyoa.cafe' in url:
        logger.warning("Cyoa.cafe link detected, attempting to find real url")
        url = get_iframe_url_from_cyoa_cafe(url)
        if not url:
            return None, ""
        logger.info(f"Corrected url: {url}")

    logger.info(f"Checking {url}")

    default_location = strip_document_from_url(url)+'project.json'

    if url_file_exists(default_location):
        return get_source(default_location), strip_document_from_url(url)

    source = get_source(url)
    if not source:
        return None, ""
    base_url = strip_document_from_url(url)
    for js_script in find_scripts(source, base_url):
        found_urls = extract_placeholder_url(js_script)
        if found_urls:
            for found_url in found_urls:
                full_url = found_url if 'http' in found_url else url.rstrip('/') + '/' + found_url
                project_source = get_source(full_url)
                if project_source:
                    logger.info("Found project file.")
                    return project_source, url

        logger.info("File not found, looking for embedded project.")
        start_string = 'Store({state:{app:'
        end_string = '},getters'

        if start_string in js_script and end_string in js_script:
            try:
                extracted = js_script.split(start_string)[-1].split(end_string)[0]
                logger.info("Found embedded project")
                return extracted, url
            except IndexError:
                logger.warning("Failed to extract embedded project JSON")

    logger.info("Failed to find embedded project, looking for iframes.")

    iframe_urls = extract_iframe_urls(source)
    for iframe_url in iframe_urls:
        logger.info(f"Checking iframe: {iframe_url}")
        project_source, project_url = get_project_source(iframe_url, depth + 1)
        if project_source:
            return project_source, project_url

    return None, ""

def url_file_exists(url: str, timeout: int = 5) -> bool:
    """
    Checks if a file exists at the given URL by sending a HEAD request.

    Parameters:
        url (str): The URL to check.
        timeout (int): Timeout for the request in seconds (default is 5).

    Returns:
        bool: True if the file exists (HTTP status code 200), False otherwise.
    """
    try:
        response = requests.head(url, allow_redirects=True, timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False

def get_iframe_url_from_cyoa_cafe(game_url: str) -> str:
    """
    Given a game URL, fetches the corresponding iframe URL from the API.

    Parameters:
        game_url (str): The URL of the game, e.g., 'https://cyoa.cafe/game/21zdlixfdt6g1vh'

    Returns:
        str: The 'iframe_url' value from the API response.

    Raises:
        ValueError: If the URL format is invalid or 'iframe_url' is not found.
        requests.RequestException: If the HTTP request fails.
    """
    # Parse the URL to extract the path
    parsed_url = urlparse(game_url)
    path_parts = parsed_url.path.strip('/').split('/')

    # Validate the URL structure
    if len(path_parts) != 2 or path_parts[0] != 'game':
        raise ValueError(f"Invalid game URL format: {game_url}")

    game_id = path_parts[1]

    # Construct the API URL
    api_url = f"https://cyoa.cafe/api/collections/games/records/{game_id}"

    try:
        # Make the GET request to the API
        response = requests.get(api_url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Parse the JSON response
        data = response.json()

        # Extract the 'iframe_url' from the JSON data
        iframe_url = data.get('iframe_url')
        if not iframe_url:
            raise ValueError(f"'iframe_url' not found in the API response for game ID: {game_id}")

        return iframe_url

    except requests.RequestException as e:
        raise requests.RequestException(f"HTTP request failed: {e}")

def extract_json_like_block(text: str) -> str:
    start = text.find('{')
    end = text.rfind('}') + 1
    if start != -1 and end != -1 and start < end:
        return text[start:end]
    return ''

def get_source(url: str) -> Optional[str]:
    try:
        response = requests.get(url)
        response.raise_for_status()
        logger.info(f"Successfully downloaded source from {url}")
        return response.text
    except requests.RequestException as e:
        logger.error(f"Error downloading {url}: {e}")
        return None

def find_scripts(html_source: str, base_url: Optional[str] = None) -> List[str]:
    soup = BeautifulSoup(html_source, 'html.parser')
    script_tags = soup.find_all('script')
    script_contents = []

    for script in script_tags:
        if 'document.createElement' in str(script):
            #this script might contain some dynamic loading bs, try to find the app.js file from it
            src = extract_app_js_path(str(script))
            if base_url and not src.startswith(('http://', 'https://')):
                src = base_url.rstrip('/') + '/' + src.lstrip('/')
            try:
                response = requests.get(src)
                if response.status_code == 200:
                    script_contents.append(response.text)
            except requests.RequestException as e:
                logger.error(f"Failed to fetch {src}: {e}")
        elif script.get('src'):
            src = script['src']
            if base_url and not src.startswith(('http://', 'https://')):
                src = base_url.rstrip('/') + '/' + src.lstrip('/')
            try:
                response = requests.get(src)
                if response.status_code == 200:
                    script_contents.append(response.text)
            except requests.RequestException as e:
                logger.error(f"Failed to fetch {src}: {e}")
        else:
            script_contents.append(script.string or '')

    return script_contents

def extract_placeholder_url(source: str) -> List[str]:
    pattern = r'\$store\.commit\("loadApp",.*?\)\}\},e\.open\("GET","(.*?)",!0\)'
    result = re.findall(pattern, source)
    if result:
        return result
    pattern = r'e\.open\(\s*["\']GET["\']\s*,\s*["\']([^"\']+)["\']'
    return re.findall(pattern, source)


def extract_iframe_urls(html_source: str) -> List[str]:
    soup = BeautifulSoup(html_source, 'html.parser')
    iframe_tags = soup.find_all('iframe')
    return [iframe.get('src') for iframe in iframe_tags if iframe.get('src')]

def get_first_folder_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    path = parsed_url.path.strip('/')
    if path:
        return path.split('/')[0]
    return ''

def extract_app_js_path(code: str) -> str:
    """
    Extracts the 'js/app.*.js' path from the provided code string.

    Parameters:
        code (str): The input string containing JavaScript code.

    Returns:
        str: The extracted JavaScript file path if found; otherwise, an empty string.
    """
    pattern = r"js/app\.[^'\"]+\.js"
    match = re.search(pattern, code)
    return match.group(0) if match else ''

def get_first_subdomain(url: str) -> str:
    """
    Extracts the first subdomain from a given URL.

    Parameters:
        url (str): The input URL.

    Returns:
        str: The first subdomain if present; otherwise, an empty string.
    """
    extracted = tldextract.extract(url)
    subdomain = extracted.subdomain
    if subdomain:
        return subdomain.split('.')[0]
    return ''

def clean_url_path_component(encoded_str: str) -> str:
    """
    Decodes a URL-encoded string and removes characters not typically found in file paths.

    Parameters:
        encoded_str (str): The URL-encoded string to clean.

    Returns:
        str: A cleaned string suitable for use in file paths.
    """
    # Decode percent-encoded characters
    decoded_str = unquote(encoded_str)

    # Define allowed characters: letters, digits, underscore, hyphen, period, and slash
    allowed_chars_pattern = r'[^A-Za-z0-9_\-./]'

    # Remove disallowed characters
    cleaned_str = re.sub(allowed_chars_pattern, '', decoded_str)

    return cleaned_str

def save_string_to_file(content: str, filename: str, path: str = "") -> None:
    """
    Saves a string to a file. The filename is cleaned of invalid characters, 
    and if the file already exists, a number is appended to the filename.

    Parameters:
        content (str): The string content to save.
        filename (str): The desired filename.
        path (str, optional): The folder path to save the file into.
    """
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    base, extension = os.path.splitext(filename)

    # Use provided path, or default to current directory
    if path:
        os.makedirs(path, exist_ok=True)
        new_filename = os.path.join(path, filename)
    else:
        new_filename = filename

    counter = 1
    while os.path.exists(new_filename):
        new_filename = os.path.join(path, f"{base}_{counter}{extension}") if path else f"{base}_{counter}{extension}"
        counter += 1

    with open(new_filename, 'w', encoding='utf-8') as file:
        file.write(content)

    logger.info(f"File saved as: {new_filename}")

def process_images(
    input_str: str,
    base_url: str,
    embed: bool = False,
    download: bool = False,
    temp_folder: str = None,
    wait_time: int = 20
) -> tuple[str, str]:
    """
    Processes image references in a JSON-like string by embedding them as base64 data URIs,
    downloading them to a local folder, or both, based on specified parameters.

    Parameters:
        input_str (str): The string containing image references.
        base_url (str): The base URL to resolve relative image paths.
        embed (bool): If True, embed images as base64 data URIs.
        download (bool): If True, download images to a local folder and update paths.
        temp_folder (str): The directory path where images will be saved if download is True.
        wait_time (int): Time in seconds to wait before retrying after a 429 response.

    Returns:
        tuple[str, str]: A tuple containing two strings:
            - The modified string with base64-encoded image references (if embed is True).
            - The modified string with local image paths (if download is True).
    """
    data_uri_pattern = re.compile(r'^data:image\/[a-zA-Z0-9.+-]+;base64,')

    if download and not temp_folder:
        raise ValueError("temp_folder must be specified when download is True.")

    if download:
        images_folder = os.path.join(temp_folder, "images")
        os.makedirs(images_folder, exist_ok=True)

    pattern = r'"image":"([^"]+)"'

    # Create separate copies of the input string for embedding and downloading
    embed_str = input_str
    download_str = input_str

    def process_match(match, operation):
        image_path = match.group(1)
        

        if data_uri_pattern.match(image_path):
            logger.info(f"Skipping already embedded image.")
            return match.group(0)

        logger.info(f"Processing image: {image_path}")
        image_url = image_path if image_path.startswith(('http://', 'https://')) else urljoin(base_url + '/', image_path)

        headers = get_headers_for_url(image_url)

        retries = 3
        for attempt in range(retries):
            try:
                response = requests.get(image_url, headers=headers)
                if response.status_code == 429:
                    logger.warning(f"Received 429 Too Many Requests for {image_url}. Waiting {wait_time} seconds before retrying...")
                    time.sleep(wait_time)
                    continue
                response.raise_for_status()

                # Determine MIME type from Content-Type header
                mime_type = response.headers.get('Content-Type')
                if not mime_type:
                    # Fallback to mimetypes module
                    mime_type, _ = mimetypes.guess_type(image_url)
                    if not mime_type:
                        mime_type = 'application/octet-stream'

                if operation == 'embed':
                    b64_data = base64.b64encode(response.content).decode('utf-8')
                    data_uri = f'data:{mime_type};base64,{b64_data}'
                    return f'"image":"{data_uri}"'

                elif operation == 'download':
                    # Determine file extension from MIME type
                    ext = mimetypes.guess_extension(mime_type)
                    if not ext:
                        ext = '.bin'

                    # Generate a safe filename
                    parsed_url = urlparse(image_url)
                    filename = os.path.basename(parsed_url.path)
                    if not filename:
                        filename = 'image'
                    if not os.path.splitext(filename)[1]:
                        filename += ext

                    save_path = os.path.join(images_folder, filename)

                    # Avoid overwriting if file already exists
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(save_path):
                        filename = f"{base}_{counter}{ext}"
                        save_path = os.path.join(images_folder, filename)
                        counter += 1

                    with open(save_path, 'wb') as f:
                        f.write(response.content)

                    logger.info(f"Saved image: {save_path}")

                    return f'"image":"images/{filename}"'

            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed for {image_url}: {e}")
                if attempt < retries - 1:
                    time.sleep(10)
                else:
                    logger.error(f"All retries failed for {image_url}.")
                    return match.group(0)
        logger.error(f"Failed to process image: {image_path}")
        return match.group(0)

    if embed:
        embed_str = re.sub(pattern, lambda m: process_match(m, 'embed'), embed_str, flags=re.IGNORECASE)
    if download:
        download_str = re.sub(pattern, lambda m: process_match(m, 'download'), download_str, flags=re.IGNORECASE)

    return embed_str, download_str

def create_random_temp_folder(prefix: str = "cyoa_") -> str:
    """
    Creates a random temporary folder that does not already exist.
    
    Parameters:
        prefix (str): Optional prefix for the folder name.

    Returns:
        str: The full path to the created temporary folder.
    """
    temp_dir = tempfile.gettempdir()
    while True:
        folder_name = prefix + uuid.uuid4().hex[:8]
        folder_path = os.path.join(temp_dir, folder_name)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
            return folder_path
        

def zip_temp_folder(temp_path: str, zip_name: str = "") -> str:
    """
    Zips the contents of a temporary folder into a zip file in the current directory.

    Parameters:
        temp_path (str): The path to the temporary folder to zip.
        zip_name (str, optional): The desired name of the zip file (without extension).
                                  If not provided, a timestamp-based name is used.

    Returns:
        str: The path to the created zip file.
    """
    if not os.path.isdir(temp_path):
        raise ValueError(f"{temp_path} is not a valid directory.")

    if not zip_name:
        zip_name = f"archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not zip_name.endswith('.zip'):
        zip_filename = f"{zip_name}.zip"
    else:
        zip_filename = f"{zip_name}"
    zip_filepath = os.path.join(os.getcwd(), zip_filename)

    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(temp_path):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, start=temp_path)
                zipf.write(abs_path, arcname=rel_path)

    logger.info(f"Created zip file: {zip_filepath}")
    return zip_filepath


def delete_temp_folder(temp_path: str) -> None:
    """
    Deletes the specified temporary folder and all of its contents.

    Parameters:
        temp_path (str): The path to the temporary folder to delete.
    """
    if os.path.isdir(temp_path):
        shutil.rmtree(temp_path)
        logger.info(f"Deleted temporary folder: {temp_path}")
    else:
        logger.warning(f"Attempted to delete non-existent folder: {temp_path}")



def strip_document_from_url(url: str) -> str:
    """
    Removes the last path segment from the URL if it does not end with a slash,
    and removes any query parameters, leaving only the directory path.

    Parameters:
        url (str): The input URL.

    Returns:
        str: The URL with the document name and query parameters removed if applicable.
    """
    parsed = urlparse(url)
    path = parsed.path

    # Only modify the path if it does not end with a slash
    if not path.endswith('/'):
        # Split the path into segments
        segments = path.split('/')
        # Remove the last segment
        segments = segments[:-1]
        # Reconstruct the path
        path = '/'.join(segments)
        # Ensure the path ends with a slash if it's not empty
        if path and not path.endswith('/'):
            path += '/'
        # If the path is empty, set it to '/'
        elif not path:
            path = '/'

    # Reconstruct the URL with the modified path and empty query
    stripped_url = urlunparse(parsed._replace(path=path, query=''))
    return stripped_url


def get_headers_for_url(url: str) -> dict | None:
    """
    Retrieves custom headers for a given URL based on its domain.

    Parameters:
        url (str): The URL for which headers are to be retrieved.

    Returns:
        dict | None: A dictionary of headers if the domain has custom headers defined; otherwise, None.

    """

    DOMAIN_HEADERS = {
    'umgur.com':{"user-agent": "curl/8.1.1","accept": "*/*"},
    # Add more domain-specific headers as needed
    }
          
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.hostname
        if domain in DOMAIN_HEADERS:
            return DOMAIN_HEADERS[domain]
        return {"User-Agent": "Mozilla/5.0", "accept-language": "en-US,en"}
    except Exception as e:
        print(f"Error parsing URL '{url}': {e}")
        return None

if __name__ == "__main__":
    main()

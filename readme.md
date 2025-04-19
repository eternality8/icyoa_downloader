CYOA Downloader

A command-line tool to download and process Choose Your Own Adventure (CYOA) projects made with InteractiveCyoaCreator or ICCPlus from web URLs. It can extract embedded or external project.json files, download associated images, and output the project as a standalone JSON file with embedded images or as a ZIP archive with external images.​
Features

    Recursively locates and extracts project.json from scripts or iframes. 

    Supports both embedded and externally hosted project files.

    Downloads all referenced images and either embeds them as base64 or saves them in a ZIP archive.

    Automatically generates filenames based on the URL structure.


Requirements

    Python 3.7 or higher

    Dependencies:

        requests

        beautifulsoup4

        tldextract​

Install the required packages using pip:​

pip install requests beautifulsoup4 tldextract

Usage

python cyoa_downloader.py [-z | --zip] [-b | --both] <url> [filename] 

Positional Arguments

    <url>: The URL of the CYOA project to download.

    [filename]: Optional output filename (without extension). If omitted, the filename is auto-generated based on the URL.​

Optional Flags

    -z, --zip: Save the project as a ZIP archive with external images.

    -b, --both: Save both an embedded JSON file and a ZIP archive.​

Examples

Download and save as an embedded JSON file:​

python cyoa_downloader.py https://example.com/cyoa

Download and save as a ZIP archive:​

python cyoa_downloader.py -z https://example.com/cyoa 

Download and save both formats:​

python cyoa_downloader.py -b https://example.com/cyoa 

How It Works

    Fetches the HTML content of the provided URL.

    Searches for scripts containing project.json references or embedded project data.

    If not found, recursively checks iframes up to a depth of 3.

    Extracts the JSON-like block representing the project.

    Depending on the chosen mode:

        Embeds images as base64 within the JSON file.

        Downloads images to a temporary folder and packages them into a ZIP archive.

    Saves the final output to the specified or auto-generated filename.​

Logging

The script provides informative logging messages to the console, detailing the progress and any issues encountered during execution.​
License

This project is licensed under the license provided in license.txt
Contributing

Contributions are welcome! Please fork the repository and submit a pull request with your enhancements.​
Acknowledgments

This tool was inspired by the need to easily download and archive CYOA projects for offline use and preservation, since you never know how long the websites stay up.
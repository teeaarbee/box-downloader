# Box Downloader

A modern, cross-platform GUI application for downloading files and folders from Box shared links. Built with Python and Tkinter.

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-macOS%20|%20Windows%20|%20Linux-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## Features

- **No Authentication Required** for public shared links
- **Dark & Light Mode** - Toggle between themes with one click
- **OAuth Token Generation** - Built-in wizard for generating Box API tokens
- **Progress Tracking** - Real-time download progress with cancel support
- **Password-Protected Links** - Support for links that require a password
- **Smart Download Methods** - Multiple fallback methods to ensure successful downloads
- **Cross-Platform** - Works on macOS, Windows, and Linux

## Screenshots

### Dark Mode
```
┌─────────────────────────────────────────────────────────┐
│  Box Downloader                    [🔑 Get Token] [☀️]  │
├─────────────────────────────────────────────────────────┤
│  Shared Link                                            │
│  ┌─────────────────────────────────────────────────┐   │
│  │ https://company.box.com/s/abc123/file/456       │   │
│  └─────────────────────────────────────────────────┘   │
│  [Fetch Info]  [🔒 Add Password]                       │
├─────────────────────────────────────────────────────────┤
│  File Information                                       │
│  ┌─────────────────────────────────────────────────┐   │
│  │ 📄 document.pdf                                  │   │
│  │ Type: File                                       │   │
│  │ Size: 2.4 MB                                     │   │
│  └─────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│  Download Options                                       │
│  Save to: /Users/you/Downloads          [Browse...]    │
│  Access Token: **********************                  │
├─────────────────────────────────────────────────────────┤
│  [████████████████████████░░░░░░] 75%                  │
│  Downloading... 1.8 MB / 2.4 MB                        │
│                                                         │
│  [⬇ Download]  [Cancel]                                │
└─────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- Python 3.9 or higher
- `requests` library

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/box-downloader.git
   cd box-downloader
   ```

2. **Create a virtual environment** (recommended)
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python box_downloader.py
   ```

### macOS Quick Launch

Double-click `launch.command` to start the application.

## Usage

### Downloading Public Files

1. Copy a Box shared link (e.g., `https://company.box.com/s/abc123xyz/file/123456`)
2. Paste the link into the "Shared Link" field
3. Click **Fetch Info** to retrieve file details
4. Choose your download location
5. Click **Download**

### Password-Protected Links

1. Enter the shared link
2. Click **🔒 Add Password**
3. Enter the password
4. Click **Fetch Info** and proceed with download

### Private Links (Requires Authentication)

For private or restricted links, you'll need a Box API access token:

1. Click **🔑 Get Token** in the top-right corner
2. Follow the OAuth setup wizard (see below)
3. The token will be automatically filled in
4. Proceed with fetching and downloading

## OAuth Token Setup

To download private files, you need to create a Box Developer application:

### Step 1: Create a Box App

1. Go to [Box Developer Console](https://developer.box.com/)
2. Click **My Apps** → **Create New App**
3. Select **Custom App**
4. Choose **User Authentication (OAuth 2.0)**
5. Name your app and click **Create App**

### Step 2: Configure Your App

1. In your app settings, go to **Configuration**
2. Under **OAuth 2.0 Redirect URI**, add: `https://localhost`
3. Copy your **Client ID** and **Client Secret**

### Step 3: Generate Token in Box Downloader

1. Click **🔑 Get Token** in the application
2. Enter your Client ID and Client Secret
3. Click **Open Browser to Authorize**
4. Log in to Box and authorize the app
5. You'll be redirected to a URL like: `https://localhost/?code=AUTHORIZATION_CODE`
6. Copy the `code` value from the URL
7. Paste it in the "Authorization Code" field
8. Click **Get Token**

Your access token is now ready to use!

> **Note:** Access tokens expire after 60 minutes. You'll need to generate a new one when it expires.

## How It Works

Box Downloader uses multiple methods to download files, trying each in order until one succeeds:

### Method 1: Direct Shared File Endpoint
For public shared links, the app uses Box's internal download endpoint:
```
https://[subdomain].box.com/index.php?rm=box_download_shared_file&shared_name=XXX&file_id=f_YYY
```
This method works without any authentication for publicly accessible links.

### Method 2: Scraped Download URL
The app parses the Box shared link page to extract embedded download URLs from the page's JavaScript data.

### Method 3: Box API with Token
For private links, the app uses the official Box API with your access token:
```
GET https://api.box.com/2.0/files/{file_id}/content
Header: Authorization: Bearer {access_token}
Header: BoxAPI: shared_link={url}
```

## Supported Link Formats

| Format | Example | Auth Required |
|--------|---------|---------------|
| Shared Link | `https://app.box.com/s/abc123xyz` | No* |
| Shared Link + File | `https://app.box.com/s/abc123xyz/file/123456` | No* |
| Direct File | `https://app.box.com/file/123456789` | Yes |
| Direct Folder | `https://app.box.com/folder/123456789` | Yes |
| Enterprise Subdomain | `https://company.box.com/s/abc123xyz` | No* |

\* May require authentication depending on the link's access settings

## Configuration

### Themes

Toggle between dark and light mode by clicking the ☀️/🌙 button in the top-right corner.

| Theme | Background | Accent |
|-------|------------|--------|
| Dark | `#1e1e1e` | `#3b82f6` |
| Light | `#f0f0f2` | `#2563eb` |

### Default Download Location

The default download location is your system's Downloads folder. Click **Browse...** to change it.

## Troubleshooting

### "Authentication required" error
- The link requires authentication. Use the **🔑 Get Token** feature to generate an access token.

### "Could not determine file ID" error
- The link format may not be supported. Try copying the full URL including any `/file/` or `/folder/` path.

### Download fails silently
- Check your internet connection
- Verify the link hasn't expired
- Try generating a new access token

### App crashes on macOS
- Make sure you're using the Homebrew Python (Python 3.9+) instead of the system Python
- Use the provided `launch.command` which uses the virtual environment

## Project Structure

```
box_downloader/
├── box_downloader.py    # Main application
├── requirements.txt     # Python dependencies
├── launch.command       # macOS launcher script
├── venv/               # Virtual environment
└── README.md           # This file
```

## Dependencies

- **requests** - HTTP library for API calls and downloads
- **tkinter** - GUI framework (included with Python)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Box API Documentation](https://developer.box.com/reference/)
- [Box Developer Community](https://community.box.com/)

## Disclaimer

This tool is not affiliated with, endorsed by, or sponsored by Box, Inc. Use it responsibly and in accordance with Box's Terms of Service.

---

**Made with ❤️ for the open-source community**

#!/usr/bin/env python3
"""
Box Downloader - A GUI tool for downloading files and folders from Box shared links.

Supports:
- Public shared links (no authentication required for open links)
- Password-protected shared links
- Files and folders (folders downloaded as ZIP)
- Progress tracking with cancel support
- OAuth token generation
- Dark mode
"""

import os
import re
import json
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlparse, urlencode
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Theme definitions
THEMES = {
    'light': {
        'bg': '#f0f0f2',
        'fg': '#1d1d1f',
        'accent': '#2563eb',  # Brighter blue
        'secondary_bg': '#ffffff',
        'info_bg': '#dce8fc',
        'border': '#b0b0b5',
        'disabled': '#6e6e73',
        'entry_bg': '#ffffff',
        'entry_fg': '#1d1d1f',
        'button_bg': '#e0e0e2',
        'button_fg': '#1d1d1f',
        'success': '#16a34a',  # Brighter green
        'error': '#dc2626',
    },
    'dark': {
        'bg': '#1e1e1e',
        'fg': '#e8e8e8',
        'accent': '#3b82f6',  # Bright blue
        'secondary_bg': '#2d2d2d',
        'info_bg': '#1e3a5f',
        'border': '#555555',
        'disabled': '#888888',
        'entry_bg': '#404040',
        'entry_fg': '#ffffff',
        'button_bg': '#4a4a4a',
        'button_fg': '#ffffff',
        'success': '#22c55e',  # Bright green
        'error': '#ef4444',
    }
}


@dataclass
class BoxItem:
    """Represents a Box file or folder."""
    item_id: str
    item_type: str  # 'file' or 'folder'
    name: str
    size: Optional[int] = None
    shared_link: str = ""


class BoxOAuth:
    """Handles Box OAuth 2.0 authentication flow."""

    AUTH_URL = "https://account.box.com/api/oauth2/authorize"
    TOKEN_URL = "https://api.box.com/oauth2/token"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_authorization_url(self, redirect_uri: str = "https://localhost") -> str:
        """Generate the authorization URL for the user to visit."""
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, auth_code: str, redirect_uri: str = "https://localhost") -> dict:
        """Exchange authorization code for access token."""
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': redirect_uri,
        }

        response = requests.post(self.TOKEN_URL, data=data)

        if response.status_code != 200:
            raise Exception(f"Token exchange failed: {response.status_code} - {response.text}")

        return response.json()


class BoxDownloader:
    """Handles downloading files and folders from Box shared links."""

    BASE_API_URL = "https://api.box.com/2.0"

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token
        self.session = self._create_session()
        self._cancelled = False

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get_headers(self, shared_link: str, password: Optional[str] = None) -> dict:
        """Build headers for Box API requests."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        boxapi_value = f"shared_link={shared_link}"
        if password:
            boxapi_value += f"&shared_link_password={password}"
        headers["boxapi"] = boxapi_value

        return headers

    def parse_shared_link(self, url: str) -> tuple[str, str]:
        """Parse a Box shared link URL to extract the shared link ID and type."""
        parsed = urlparse(url)
        path = parsed.path

        if '/file/' in path:
            match = re.search(r'/file/(\d+)', path)
            if match:
                return match.group(1), 'file'

        if '/folder/' in path:
            match = re.search(r'/folder/(\d+)', path)
            if match:
                return match.group(1), 'folder'

        return url, 'shared_link'

    def get_shared_item_info(self, shared_link: str, password: Optional[str] = None) -> BoxItem:
        """Get information about a shared item using the Box API."""
        headers = self._get_headers(shared_link, password)

        response = self.session.get(
            f"{self.BASE_API_URL}/shared_items",
            headers=headers
        )

        if response.status_code == 401:
            raise PermissionError("Authentication required. Please provide an access token.")
        elif response.status_code == 403:
            if "password" in response.text.lower():
                raise PermissionError("This shared link is password protected.")
            raise PermissionError("Access denied. The shared link may have expired.")
        elif response.status_code != 200:
            raise Exception(f"Failed to get shared item info: {response.status_code}")

        data = response.json()
        return BoxItem(
            item_id=data.get("id", ""),
            item_type=data.get("type", "file"),
            name=data.get("name", "download"),
            size=data.get("size"),
            shared_link=shared_link
        )

    def _extract_shared_name_and_file_id(self, url: str) -> tuple[Optional[str], Optional[str], str]:
        """Extract the shared_name and file_id from a Box URL."""
        parsed = urlparse(url)

        shared_match = re.search(r'/s/([a-zA-Z0-9]+)', url)
        shared_name = shared_match.group(1) if shared_match else None

        file_match = re.search(r'/file/(\d+)', url)
        file_id = file_match.group(1) if file_match else None

        return shared_name, file_id, parsed.netloc

    def _scrape_download_info(self, shared_link: str, password: Optional[str] = None) -> Optional[dict]:
        """Scrape download information from the Box shared link page."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            response = self.session.get(shared_link, headers=headers, allow_redirects=True)
            if response.status_code != 200:
                return None

            html = response.text
            info = {}

            name_match = re.search(r'"name"\s*:\s*"([^"]+)"', html)
            if name_match:
                info['name'] = name_match.group(1)

            typed_id_match = re.search(r'"typedID"\s*:\s*"([fd])_(\d+)"', html)
            if typed_id_match:
                info['type'] = 'file' if typed_id_match.group(1) == 'f' else 'folder'
                info['id'] = typed_id_match.group(2)

            size_match = re.search(r'"size"\s*:\s*(\d+)', html)
            if size_match:
                info['size'] = int(size_match.group(1))

            return info if info else None

        except Exception as e:
            print(f"Scraping failed: {e}")
            return None

    def download_shared_file(self, shared_link: str, dest_path: str,
                              progress_callback: Optional[Callable[[int, int], None]] = None) -> str:
        """Download a file using Box's internal shared file download endpoint."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

        shared_name, file_id, netloc = self._extract_shared_name_and_file_id(shared_link)

        if not shared_name:
            raise Exception("Could not extract shared name from URL")

        if not file_id:
            info = self._scrape_download_info(shared_link)
            if info and info.get('id'):
                file_id = info['id']
            else:
                raise Exception("Could not determine file ID from URL")

        download_endpoint = f"https://{netloc}/index.php"
        params = {
            'rm': 'box_download_shared_file',
            'shared_name': shared_name,
            'file_id': f'f_{file_id}',
        }

        response = self.session.get(download_endpoint, params=params, headers=headers, allow_redirects=False)

        if response.status_code == 302:
            download_url = response.headers.get('Location')
            if not download_url:
                raise Exception("No download URL in redirect")
        else:
            raise Exception(f"Failed to get download URL: {response.status_code}")

        response = self.session.get(download_url, headers=headers, stream=True)
        if response.status_code != 200:
            raise Exception(f"Download failed: {response.status_code}")

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if self._cancelled:
                    raise InterruptedError("Download cancelled")
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        return dest_path

    def download_file(self, file_id: str, shared_link: str, dest_path: str,
                      password: Optional[str] = None,
                      progress_callback: Optional[Callable[[int, int], None]] = None) -> str:
        """Download a file from Box using the API."""
        headers = self._get_headers(shared_link, password)

        response = self.session.get(
            f"{self.BASE_API_URL}/files/{file_id}/content",
            headers=headers,
            allow_redirects=False
        )

        if response.status_code == 302:
            download_url = response.headers.get("Location")
        elif response.status_code == 200:
            download_url = None
            content = response.content
        else:
            raise Exception(f"Failed to get download URL: {response.status_code}")

        if download_url:
            response = self.session.get(download_url, stream=True)
            if response.status_code != 200:
                raise Exception(f"Download failed: {response.status_code}")

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self._cancelled:
                        raise InterruptedError("Download cancelled")
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
        else:
            with open(dest_path, 'wb') as f:
                f.write(content)
            if progress_callback:
                progress_callback(len(content), len(content))

        return dest_path

    def download_from_direct_url(self, url: str, dest_path: str,
                                  progress_callback: Optional[Callable[[int, int], None]] = None) -> str:
        """Download from a direct URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        }

        response = self.session.get(url, headers=headers, stream=True)
        if response.status_code != 200:
            raise Exception(f"Download failed: {response.status_code}")

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if self._cancelled:
                    raise InterruptedError("Download cancelled")
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size)

        return dest_path

    def cancel(self):
        """Cancel any ongoing download."""
        self._cancelled = True

    def reset(self):
        """Reset the cancelled state."""
        self._cancelled = False


class OAuthDialog(tk.Toplevel):
    """Dialog for generating Box OAuth access tokens."""

    def __init__(self, parent, theme: dict):
        super().__init__(parent)
        self.title("Generate Access Token")
        self.geometry("550x480")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.theme = theme
        self.access_token = None
        self.configure(bg=theme['bg'])

        self._create_widgets()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        theme = self.theme

        main_frame = tk.Frame(self, bg=theme['bg'], padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main_frame, text="Box OAuth Setup", font=("Helvetica", 16, "bold"),
                 bg=theme['bg'], fg=theme['fg']).pack(anchor=tk.W)

        tk.Label(main_frame, text="Generate an access token using your Box Developer credentials",
                 bg=theme['bg'], fg=theme['disabled']).pack(anchor=tk.W, pady=(0, 15))

        # Instructions
        instructions = """Steps:
1. Go to developer.box.com and create an app
2. Get your Client ID and Client Secret
3. Enter them below and click 'Open Browser'
4. Authorize the app and copy the code from the URL
5. Paste the code and click 'Get Token'"""

        instr_label = tk.Label(main_frame, text=instructions, justify=tk.LEFT,
                               bg=theme['info_bg'], fg=theme['fg'], padx=12, pady=12,
                               anchor=tk.W, relief=tk.FLAT)
        instr_label.pack(fill=tk.X, pady=(0, 15))

        # Client ID
        tk.Label(main_frame, text="Client ID:", bg=theme['bg'], fg=theme['fg'],
                 font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(5, 2))
        self.client_id_var = tk.StringVar()
        self.client_id_entry = tk.Entry(main_frame, textvariable=self.client_id_var,
                                         bg=theme['entry_bg'], fg=theme['entry_fg'],
                                         insertbackground=theme['entry_fg'], width=60,
                                         relief=tk.SOLID, bd=1,
                                         highlightbackground=theme['border'],
                                         highlightcolor=theme['accent'],
                                         highlightthickness=1)
        self.client_id_entry.pack(fill=tk.X, pady=(0, 8), ipady=4)

        # Client Secret
        tk.Label(main_frame, text="Client Secret:", bg=theme['bg'], fg=theme['fg'],
                 font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(5, 2))
        self.client_secret_var = tk.StringVar()
        self.client_secret_entry = tk.Entry(main_frame, textvariable=self.client_secret_var,
                                             bg=theme['entry_bg'], fg=theme['entry_fg'],
                                             insertbackground=theme['entry_fg'], width=60, show="*",
                                             relief=tk.SOLID, bd=1,
                                             highlightbackground=theme['border'],
                                             highlightcolor=theme['accent'],
                                             highlightthickness=1)
        self.client_secret_entry.pack(fill=tk.X, pady=(0, 12), ipady=4)

        # Open Browser button - using Label for reliable macOS styling
        browser_btn_frame = tk.Frame(main_frame, bg=theme['accent'])
        browser_btn_frame.pack(pady=(8, 18))
        self.open_browser_btn = tk.Label(browser_btn_frame,
                                          text="  🌐  Open Browser to Authorize  ",
                                          font=("Helvetica", 12, "bold"),
                                          bg=theme['accent'], fg='#ffffff',
                                          padx=20, pady=10, cursor="hand2")
        self.open_browser_btn.pack()
        self.open_browser_btn.bind("<Button-1>", lambda e: self._open_browser())
        self.open_browser_btn.bind("<Enter>", lambda e: self.open_browser_btn.configure(bg='#1d4ed8'))
        self.open_browser_btn.bind("<Leave>", lambda e: self.open_browser_btn.configure(bg=theme['accent']))

        # Authorization Code
        tk.Label(main_frame, text="Authorization Code (from redirect URL):",
                 bg=theme['bg'], fg=theme['fg'],
                 font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(5, 2))
        self.auth_code_var = tk.StringVar()
        self.auth_code_entry = tk.Entry(main_frame, textvariable=self.auth_code_var,
                                         bg=theme['entry_bg'], fg=theme['entry_fg'],
                                         insertbackground=theme['entry_fg'], width=60,
                                         relief=tk.SOLID, bd=1,
                                         highlightbackground=theme['border'],
                                         highlightcolor=theme['accent'],
                                         highlightthickness=1)
        self.auth_code_entry.pack(fill=tk.X, pady=(0, 12), ipady=4)

        # Get Token button - using Label for reliable macOS styling
        btn_frame = tk.Frame(main_frame, bg=theme['bg'])
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        get_token_frame = tk.Frame(btn_frame, bg=theme['success'])
        get_token_frame.pack(side=tk.LEFT)
        self.get_token_btn = tk.Label(get_token_frame, text="  ✓  Get Token  ",
                                       font=("Helvetica", 11, "bold"),
                                       bg=theme['success'], fg='#ffffff',
                                       padx=15, pady=8, cursor="hand2")
        self.get_token_btn.pack()
        self.get_token_btn.bind("<Button-1>", lambda e: self._get_token())
        self.get_token_btn.bind("<Enter>", lambda e: self.get_token_btn.configure(bg='#15803d'))
        self.get_token_btn.bind("<Leave>", lambda e: self.get_token_btn.configure(bg=theme['success']))

        cancel_frame = tk.Frame(btn_frame, bg=theme['button_bg'])
        cancel_frame.pack(side=tk.LEFT, padx=(12, 0))
        cancel_btn = tk.Label(cancel_frame, text="  Cancel  ",
                              font=("Helvetica", 11),
                              bg=theme['button_bg'], fg=theme['button_fg'],
                              padx=15, pady=8, cursor="hand2")
        cancel_btn.pack()
        cancel_btn.bind("<Button-1>", lambda e: self.destroy())
        cancel_btn.bind("<Enter>", lambda e: cancel_btn.configure(bg=theme['border']))
        cancel_btn.bind("<Leave>", lambda e: cancel_btn.configure(bg=theme['button_bg']))

        # Status
        self.status_var = tk.StringVar()
        self.status_label = tk.Label(main_frame, textvariable=self.status_var,
                                      bg=theme['bg'], fg=theme['accent'],
                                      font=("Helvetica", 10),
                                      wraplength=500)
        self.status_label.pack(pady=(15, 0))

    def _open_browser(self):
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()

        if not client_id or not client_secret:
            messagebox.showwarning("Missing Info", "Please enter both Client ID and Client Secret.")
            return

        oauth = BoxOAuth(client_id, client_secret)
        auth_url = oauth.get_authorization_url()

        self.status_var.set("Browser opened. Authorize and copy the 'code' parameter from the redirect URL.")
        webbrowser.open(auth_url)

    def _get_token(self):
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()
        auth_code = self.auth_code_var.get().strip()

        if not all([client_id, client_secret, auth_code]):
            messagebox.showwarning("Missing Info", "Please fill in all fields.")
            return

        try:
            self.status_var.set("Exchanging code for token...")
            self.update()

            oauth = BoxOAuth(client_id, client_secret)
            token_data = oauth.exchange_code_for_token(auth_code)

            self.access_token = token_data.get('access_token')

            if self.access_token:
                self.status_var.set("Token obtained successfully!")
                messagebox.showinfo("Success", "Access token obtained! It will be used for downloads.")
                self.destroy()
            else:
                self.status_var.set("No access token in response")

        except Exception as e:
            self.status_var.set(f"Error: {str(e)}")
            messagebox.showerror("Error", f"Failed to get token:\n{str(e)}")


class BoxDownloaderGUI:
    """Tkinter GUI for the Box Downloader."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Box Downloader")
        self.root.geometry("720x580")
        self.root.minsize(650, 550)

        # Theme state
        self.current_theme = 'dark'  # Start with dark mode
        self.theme = THEMES[self.current_theme]

        self.downloader = BoxDownloader()
        self.download_thread = None
        self.current_item_info = None

        self._create_widgets()
        self._apply_theme()

    def _apply_theme(self):
        """Apply the current theme to all widgets."""
        theme = self.theme

        self.root.configure(bg=theme['bg'])

        # Configure ttk styles
        style = ttk.Style()
        style.theme_use('clam')

        style.configure("TFrame", background=theme['bg'])
        style.configure("TLabel", background=theme['bg'], foreground=theme['fg'])
        style.configure("TLabelframe", background=theme['bg'], bordercolor=theme['border'])
        style.configure("TLabelframe.Label", background=theme['bg'], foreground=theme['fg'],
                       font=("Helvetica", 11, "bold"))
        style.configure("TButton", background=theme['button_bg'], foreground=theme['button_fg'],
                       padding=(10, 5))
        style.map("TButton",
                  background=[('active', theme['accent']), ('pressed', theme['accent'])],
                  foreground=[('active', '#ffffff'), ('pressed', '#ffffff')])

        style.configure("TEntry", fieldbackground=theme['entry_bg'], foreground=theme['entry_fg'],
                       insertcolor=theme['entry_fg'], bordercolor=theme['border'],
                       lightcolor=theme['border'], darkcolor=theme['border'])

        style.configure("TProgressbar", background=theme['accent'], troughcolor=theme['secondary_bg'],
                       bordercolor=theme['border'])

        style.configure("Accent.TButton", background=theme['accent'], foreground='#ffffff',
                       font=("Helvetica", 11, "bold"), padding=(15, 8))
        style.map("Accent.TButton",
                  background=[('active', theme['accent']), ('pressed', theme['accent'])],
                  foreground=[('active', '#ffffff'), ('pressed', '#ffffff')])

        # Update specific widgets
        if hasattr(self, 'info_label'):
            self.info_label.configure(background=theme['info_bg'], foreground=theme['fg'])

        if hasattr(self, 'theme_btn'):
            icon = "☀️" if self.current_theme == 'dark' else "🌙"
            self.theme_btn.configure(text=icon, bg=theme['bg'], fg=theme['fg'],
                                     activebackground=theme['bg'], activeforeground=theme['fg'])

        if hasattr(self, 'oauth_btn'):
            self.oauth_btn.configure(bg=theme['accent'], fg='#ffffff')

    def _toggle_theme(self):
        """Toggle between light and dark mode."""
        self.current_theme = 'light' if self.current_theme == 'dark' else 'dark'
        self.theme = THEMES[self.current_theme]
        self._apply_theme()
        # Recreate widgets to fully apply theme
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        self._create_content()
        self._apply_theme()

    def _create_widgets(self):
        """Create all GUI widgets."""
        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self._create_content()

    def _create_content(self):
        """Create the main content."""
        theme = self.theme

        # Title bar with theme toggle
        title_frame = ttk.Frame(self.main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(title_frame, text="Box Downloader",
                  font=("Helvetica", 18, "bold")).pack(side=tk.LEFT)

        # Theme toggle button
        icon = "☀️" if self.current_theme == 'dark' else "🌙"
        self.theme_btn = tk.Button(title_frame, text=icon, command=self._toggle_theme,
                                    font=("Helvetica", 16), bd=0, padx=8, pady=4,
                                    bg=theme['bg'], fg=theme['fg'],
                                    activebackground=theme['bg'], activeforeground=theme['fg'],
                                    cursor="hand2")
        self.theme_btn.pack(side=tk.RIGHT)

        # OAuth button - using frame wrapper for reliable macOS styling
        oauth_frame = tk.Frame(title_frame, bg=theme['accent'], padx=2, pady=2)
        oauth_frame.pack(side=tk.RIGHT, padx=(0, 15))
        self.oauth_btn = tk.Label(oauth_frame, text="🔑 Get Token",
                                   font=("Helvetica", 11, "bold"),
                                   bg=theme['accent'], fg='#ffffff',
                                   padx=12, pady=6, cursor="hand2")
        self.oauth_btn.pack()
        self.oauth_btn.bind("<Button-1>", lambda e: self._show_oauth_dialog())
        self.oauth_btn.bind("<Enter>", lambda e: self.oauth_btn.configure(bg='#1d4ed8'))
        self.oauth_btn.bind("<Leave>", lambda e: self.oauth_btn.configure(bg=theme['accent']))

        # URL Input Section
        url_frame = ttk.LabelFrame(self.main_frame, text="Shared Link", padding=15)
        url_frame.pack(fill=tk.X, pady=(0, 10))

        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("Helvetica", 11))
        url_entry.pack(fill=tk.X, pady=(0, 10))
        url_entry.bind('<Return>', lambda e: self.fetch_info())

        # Password field (initially hidden)
        self.password_frame = ttk.Frame(url_frame)
        ttk.Label(self.password_frame, text="Password:").pack(side=tk.LEFT)
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(self.password_frame, textvariable=self.password_var,
                                         show="*", width=30)
        self.password_entry.pack(side=tk.LEFT, padx=(10, 0))

        # Fetch button row
        btn_frame = ttk.Frame(url_frame)
        btn_frame.pack(fill=tk.X)

        self.fetch_btn = ttk.Button(btn_frame, text="Fetch Info", command=self.fetch_info)
        self.fetch_btn.pack(side=tk.LEFT)

        self.show_password_btn = ttk.Button(btn_frame, text="🔒 Add Password",
                                             command=self.toggle_password_field)
        self.show_password_btn.pack(side=tk.LEFT, padx=(10, 0))

        # Info display
        info_frame = ttk.LabelFrame(self.main_frame, text="File Information", padding=15)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        self.info_label = tk.Label(info_frame, text="Enter a Box shared link and click 'Fetch Info'",
                                    font=("Helvetica", 10), bg=theme['info_bg'], fg=theme['fg'],
                                    padx=10, pady=10, anchor=tk.W, justify=tk.LEFT,
                                    wraplength=600)
        self.info_label.pack(fill=tk.X)

        # Download options
        options_frame = ttk.LabelFrame(self.main_frame, text="Download Options", padding=15)
        options_frame.pack(fill=tk.X, pady=(0, 10))

        # Destination folder
        dest_frame = ttk.Frame(options_frame)
        dest_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(dest_frame, text="Save to:").pack(side=tk.LEFT)
        self.dest_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.dest_entry = ttk.Entry(dest_frame, textvariable=self.dest_var, width=50)
        self.dest_entry.pack(side=tk.LEFT, padx=(10, 10), fill=tk.X, expand=True)
        ttk.Button(dest_frame, text="Browse...", command=self.browse_destination).pack(side=tk.LEFT)

        # Access token (optional)
        token_frame = ttk.Frame(options_frame)
        token_frame.pack(fill=tk.X)

        ttk.Label(token_frame, text="Access Token:").pack(side=tk.LEFT)
        self.token_var = tk.StringVar()
        self.token_entry = ttk.Entry(token_frame, textvariable=self.token_var, width=45, show="*")
        self.token_entry.pack(side=tk.LEFT, padx=(10, 10))

        ttk.Label(token_frame, text="(optional - for private links)",
                  foreground=theme['disabled']).pack(side=tk.LEFT)

        # Progress section
        progress_frame = ttk.Frame(self.main_frame)
        progress_frame.pack(fill=tk.X, pady=(10, 10))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var,
                                             maximum=100, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(progress_frame, textvariable=self.status_var)
        self.status_label.pack(anchor=tk.W)

        # Action buttons
        action_frame = ttk.Frame(self.main_frame)
        action_frame.pack(fill=tk.X, pady=(10, 0))

        self.download_btn = ttk.Button(action_frame, text="⬇ Download",
                                        command=self.start_download, style="Accent.TButton")
        self.download_btn.pack(side=tk.LEFT, ipadx=20, ipady=5)
        self.download_btn.state(['disabled'])

        self.cancel_btn = ttk.Button(action_frame, text="Cancel", command=self.cancel_download)
        self.cancel_btn.pack(side=tk.LEFT, padx=(10, 0))
        self.cancel_btn.state(['disabled'])

        # Help text
        help_text = "Tip: Click '🔑 Get Token' to generate an access token for private links."
        ttk.Label(self.main_frame, text=help_text,
                  foreground=theme['disabled'], wraplength=650).pack(pady=(15, 0))

    def _show_oauth_dialog(self):
        """Show the OAuth token generation dialog."""
        dialog = OAuthDialog(self.root, self.theme)
        self.root.wait_window(dialog)

        if dialog.access_token:
            self.token_var.set(dialog.access_token)
            self.status_var.set("Access token set!")

    def toggle_password_field(self):
        """Show/hide the password input field."""
        if self.password_frame.winfo_ismapped():
            self.password_frame.pack_forget()
            self.show_password_btn.configure(text="🔒 Add Password")
        else:
            self.password_frame.pack(fill=tk.X, pady=(0, 10))
            self.show_password_btn.configure(text="🔓 Hide Password")
            self.password_entry.focus()

    def browse_destination(self):
        """Open folder browser dialog."""
        folder = filedialog.askdirectory(initialdir=self.dest_var.get())
        if folder:
            self.dest_var.set(folder)

    def fetch_info(self):
        """Fetch information about the shared link."""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Input Required", "Please enter a Box shared link.")
            return

        if not any(domain in url for domain in ['box.com', 'box.net']):
            messagebox.showwarning("Invalid URL", "Please enter a valid Box shared link.")
            return

        self.status_var.set("Fetching information...")
        self.fetch_btn.state(['disabled'])
        self.download_btn.state(['disabled'])

        token = self.token_var.get().strip()
        self.downloader = BoxDownloader(access_token=token if token else None)

        thread = threading.Thread(target=self._fetch_info_thread, args=(url,))
        thread.daemon = True
        thread.start()

    def _fetch_info_thread(self, url: str):
        """Background thread for fetching info."""
        password = self.password_var.get() if self.password_var.get() else None

        try:
            scraped_info = self.downloader._scrape_download_info(url, password)

            if scraped_info and scraped_info.get('id'):
                item_type = scraped_info.get('type', 'file')
                name = scraped_info.get('name', 'download')
                size = scraped_info.get('size', 0)
                download_url = scraped_info.get('download_url')

                self.current_item_info = {
                    'id': scraped_info['id'],
                    'type': item_type,
                    'name': name,
                    'size': size,
                    'shared_link': url,
                    'direct_download_url': download_url
                }

                size_str = self._format_size(size) if size else "Unknown size"
                type_icon = "📁" if item_type == 'folder' else "📄"
                info_text = f"{type_icon} {name}\nType: {item_type.title()}\nSize: {size_str}"

                self.root.after(0, lambda: self._update_info_display(info_text, success=True))
            else:
                try:
                    item = self.downloader.get_shared_item_info(url, password)
                    self.current_item_info = {
                        'id': item.item_id,
                        'type': item.item_type,
                        'name': item.name,
                        'size': item.size,
                        'shared_link': url,
                        'direct_download_url': None
                    }

                    size_str = self._format_size(item.size) if item.size else "Unknown size"
                    type_icon = "📁" if item.item_type == "folder" else "📄"
                    info_text = f"{type_icon} {item.name}\nType: {item.item_type.title()}\nSize: {size_str}"

                    self.root.after(0, lambda: self._update_info_display(info_text, success=True))
                except PermissionError as e:
                    self.root.after(0, lambda: self._update_info_display(str(e), success=False))
                except Exception:
                    self.current_item_info = {
                        'id': None,
                        'type': 'file',
                        'name': 'download',
                        'size': None,
                        'shared_link': url,
                        'direct_download_url': None,
                        'try_direct': True
                    }
                    info_text = "Could not fetch details, but will attempt download."
                    self.root.after(0, lambda: self._update_info_display(info_text, success=True))

        except Exception as e:
            self.root.after(0, lambda: self._update_info_display(f"Error: {str(e)}", success=False))

    def _update_info_display(self, text: str, success: bool):
        """Update the info display on the main thread."""
        self.info_label.configure(text=text)
        self.fetch_btn.state(['!disabled'])

        if success:
            self.download_btn.state(['!disabled'])
            self.status_var.set("Ready to download")
        else:
            self.download_btn.state(['disabled'])
            self.status_var.set("Could not fetch information")

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes to human-readable size."""
        if size_bytes is None:
            return "Unknown"

        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    def start_download(self):
        """Start the download process."""
        if not self.current_item_info:
            messagebox.showwarning("No File", "Please fetch file information first.")
            return

        dest_folder = self.dest_var.get()
        if not os.path.isdir(dest_folder):
            messagebox.showwarning("Invalid Path", "Please select a valid download folder.")
            return

        self.download_btn.state(['disabled'])
        self.cancel_btn.state(['!disabled'])
        self.fetch_btn.state(['disabled'])
        self.progress_var.set(0)
        self.downloader.reset()

        self.download_thread = threading.Thread(target=self._download_thread, args=(dest_folder,))
        self.download_thread.daemon = True
        self.download_thread.start()

    def _download_thread(self, dest_folder: str):
        """Background thread for downloading."""
        info = self.current_item_info
        password = self.password_var.get() if self.password_var.get() else None

        try:
            name = info.get('name', 'download')
            if info['type'] == 'folder':
                name = f"{name}.zip"

            dest_path = os.path.join(dest_folder, name)

            if os.path.exists(dest_path):
                base, ext = os.path.splitext(dest_path)
                counter = 1
                while os.path.exists(f"{base}_{counter}{ext}"):
                    counter += 1
                dest_path = f"{base}_{counter}{ext}"

            self.root.after(0, lambda: self.status_var.set(f"Downloading: {name}"))

            shared_link = info['shared_link']
            downloaded = False

            # Method 1: Box's internal shared file download endpoint
            if '/s/' in shared_link and info['type'] == 'file':
                try:
                    self.downloader.download_shared_file(
                        shared_link,
                        dest_path,
                        progress_callback=self._update_progress
                    )
                    downloaded = True
                except Exception as e:
                    print(f"Shared file download failed: {e}")

            # Method 2: Direct download URL if scraped
            if not downloaded and info.get('direct_download_url'):
                try:
                    self.downloader.download_from_direct_url(
                        info['direct_download_url'],
                        dest_path,
                        progress_callback=self._update_progress
                    )
                    downloaded = True
                except Exception as e:
                    print(f"Direct URL download failed: {e}")

            # Method 3: API download with token
            if not downloaded and info.get('id') and self.downloader.access_token:
                try:
                    self.downloader.download_file(
                        info['id'],
                        shared_link,
                        dest_path,
                        password=password,
                        progress_callback=self._update_progress
                    )
                    downloaded = True
                except Exception as e:
                    print(f"API download failed: {e}")

            if not downloaded:
                raise Exception("Could not download file. The link may require authentication.")

            self.root.after(0, lambda: self._download_complete(dest_path))

        except InterruptedError:
            self.root.after(0, lambda: self._download_cancelled())
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self._download_error(error_msg))

    def _update_progress(self, downloaded: int, total: int):
        """Update progress bar from download thread."""
        if total > 0:
            percent = (downloaded / total) * 100
            size_info = f"{self._format_size(downloaded)} / {self._format_size(total)}"
        else:
            percent = 0
            size_info = f"{self._format_size(downloaded)}"

        self.root.after(0, lambda: self.progress_var.set(percent))
        self.root.after(0, lambda: self.status_var.set(f"Downloading... {size_info}"))

    def _download_complete(self, path: str):
        """Handle download completion."""
        self.progress_var.set(100)
        self.status_var.set(f"✓ Downloaded to: {path}")
        self.download_btn.state(['!disabled'])
        self.cancel_btn.state(['disabled'])
        self.fetch_btn.state(['!disabled'])
        messagebox.showinfo("Download Complete", f"File saved to:\n{path}")

    def _download_cancelled(self):
        """Handle download cancellation."""
        self.status_var.set("Download cancelled")
        self.progress_var.set(0)
        self.download_btn.state(['!disabled'])
        self.cancel_btn.state(['disabled'])
        self.fetch_btn.state(['!disabled'])

    def _download_error(self, error: str):
        """Handle download error."""
        self.status_var.set(f"Error: {error}")
        self.progress_var.set(0)
        self.download_btn.state(['!disabled'])
        self.cancel_btn.state(['disabled'])
        self.fetch_btn.state(['!disabled'])
        messagebox.showerror("Download Error", error)

    def cancel_download(self):
        """Cancel the current download."""
        self.downloader.cancel()
        self.status_var.set("Cancelling...")

    def run(self):
        """Start the GUI application."""
        self.root.mainloop()


def main():
    """Entry point for the application."""
    app = BoxDownloaderGUI()
    app.run()


if __name__ == "__main__":
    main()

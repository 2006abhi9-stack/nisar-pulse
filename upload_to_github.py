import os
import sys
import json
import base64
import urllib.request
import urllib.error

IGNORE_DIRS = {
    '.git', '.venv', 'venv', 'ENV', 'node_modules', '__pycache__',
    'dist', '.vite', '.vscode', '.idea', 'temp_node_installer',
    '.tools', 'temp_tools'
}

IGNORE_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd', '.db', '.sqlite3', '.log', '.zip',
    '.tar.gz', '.tif', '.tiff', '.msi'
}

def is_ignored(rel_path: str) -> bool:
    parts = rel_path.replace('\\', '/').split('/')
    for p in parts:
        if p in IGNORE_DIRS:
            return True
    filename = parts[-1].lower()
    if filename == '.env' or filename.startswith('.env.') or filename.endswith('.env'):
        return True
    _, ext = os.path.splitext(rel_path)
    if ext.lower() in IGNORE_EXTENSIONS:
        return True
    if rel_path.replace('\\', '/').startswith('storage/masks/') and not rel_path.endswith('.gitkeep'):
        return True
    return False

def github_api_request(url: str, token: str, data: dict = None, method: str = None) -> dict:
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'NISAR-Pulse-Deployer'
    }
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            if content:
                return json.loads(content.decode('utf-8'))
            return {}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8')
        raise RuntimeError(f"GitHub API Error {e.code} on {url}: {err_msg}")

def upload_project(token: str, repo_name: str, private: bool = False, owner: str = None):
    # 1. Get current authenticated user
    print("[1/6] Verifying GitHub authentication...")
    user_info = github_api_request('https://api.github.com/user', token)
    username = user_info.get('login')
    if not username:
        raise ValueError("Could not retrieve GitHub user profile from provided token.")
    
    target_owner = owner if owner else username
    print(f"Authenticated as: {username}. Target repository: {target_owner}/{repo_name}")

    # 2. Check if repository exists, create if not
    print("[2/6] Checking repository status...")
    repo_exists = False
    try:
        github_api_request(f'https://api.github.com/repos/{target_owner}/{repo_name}', token)
        repo_exists = True
        print(f"Repository {target_owner}/{repo_name} already exists.")
    except RuntimeError as e:
        if "404" in str(e):
            print(f"Creating new repository: {target_owner}/{repo_name}...")
            payload = {
                'name': repo_name,
                'private': private,
                'description': 'NISAR-Pulse: SAR-Based Surface Change & Disaster Tracking Engine',
                'auto_init': False
            }
            if owner and owner != username:
                # Organization repo
                github_api_request(f'https://api.github.com/orgs/{owner}/repos', token, data=payload, method='POST')
            else:
                # Personal repo
                github_api_request('https://api.github.com/user/repos', token, data=payload, method='POST')
            print("Repository created successfully.")
        else:
            raise

    # 2b. Check if repository is empty; if so, seed an initial commit via Contents API
    try:
        github_api_request(f'https://api.github.com/repos/{target_owner}/{repo_name}/branches/main', token)
    except RuntimeError:
        print("Repository is uninitialized. Seeding initial commit via Contents API...")
        seed_content = base64.b64encode(b"# NISAR-Pulse\nSAR Surface Change & Disaster Tracking Engine\n").decode('utf-8')
        github_api_request(
            f'https://api.github.com/repos/{target_owner}/{repo_name}/contents/README.md',
            token,
            data={
                'message': 'Initial commit: repository initialization',
                'content': seed_content,
                'branch': 'main'
            },
            method='PUT'
        )
        print("Initial commit created.")

    # 3. Collect files
    print("[3/6] Scanning and staging local files...")
    root_dir = os.path.dirname(os.path.abspath(__file__))
    files_to_upload = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Prune ignored directories in-place
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for f in filenames:
            full_path = os.path.join(dirpath, f)
            rel_path = os.path.relpath(full_path, root_dir)
            if not is_ignored(rel_path):
                files_to_upload.append((rel_path, full_path))

    print(f"Found {len(files_to_upload)} files to upload.")

    # 4. Upload blobs to GitHub
    print("[4/6] Uploading file blobs to GitHub...")
    tree_items = []
    for idx, (rel_path, full_path) in enumerate(files_to_upload, start=1):
        with open(full_path, 'rb') as fp:
            raw_bytes = fp.read()
        b64_content = base64.b64encode(raw_bytes).decode('utf-8')
        
        blob_res = github_api_request(
            f'https://api.github.com/repos/{target_owner}/{repo_name}/git/blobs',
            token,
            data={'content': b64_content, 'encoding': 'base64'},
            method='POST'
        )
        blob_sha = blob_res['sha']
        
        # Git tree mode: 100755 for executable scripts, 100644 for standard files
        is_exec = rel_path.endswith('.sh') or rel_path.endswith('.bat') or rel_path.endswith('.ps1')
        mode = '100755' if is_exec else '100644'
        
        git_path = rel_path.replace('\\', '/')
        tree_items.append({
            'path': git_path,
            'mode': mode,
            'type': 'blob',
            'sha': blob_sha
        })
        if idx % 10 == 0 or idx == len(files_to_upload):
            print(f"  Uploaded {idx}/{len(files_to_upload)} files...")

    # 5. Create Git tree
    print("[5/6] Creating Git tree object...")
    tree_res = github_api_request(
        f'https://api.github.com/repos/{target_owner}/{repo_name}/git/trees',
        token,
        data={'tree': tree_items},
        method='POST'
    )
    tree_sha = tree_res['sha']

    # 6. Check existing head commit (if any)
    parents = []
    ref_exists = False
    try:
        ref_data = github_api_request(f'https://api.github.com/repos/{target_owner}/{repo_name}/git/refs/heads/main', token)
        parents.append(ref_data['object']['sha'])
        ref_exists = True
    except RuntimeError:
        pass

    # Create Commit
    commit_res = github_api_request(
        f'https://api.github.com/repos/{target_owner}/{repo_name}/git/commits',
        token,
        data={
            'message': 'Deploy NISAR-Pulse: full-stack SAR disaster platform with Docker & Render config',
            'tree': tree_sha,
            'parents': parents
        },
        method='POST'
    )
    commit_sha = commit_res['sha']

    # Update or create refs/heads/main
    print("[6/6] Finalizing main branch reference...")
    if ref_exists:
        github_api_request(
            f'https://api.github.com/repos/{target_owner}/{repo_name}/git/refs/heads/main',
            token,
            data={'sha': commit_sha, 'force': True},
            method='PATCH'
        )
    else:
        github_api_request(
            f'https://api.github.com/repos/{target_owner}/{repo_name}/git/refs',
            token,
            data={'ref': 'refs/heads/main', 'sha': commit_sha},
            method='POST'
        )

    print("\n=======================================================")
    print(f" SUCCESS! Repository is live at: https://github.com/{target_owner}/{repo_name}")
    print("=======================================================\n")
    return f"https://github.com/{target_owner}/{repo_name}"

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Upload project directly to GitHub without Git CLI.")
    token_default = os.getenv('GITHUB_TOKEN')
    parser.add_argument('--token', default=token_default, required=(token_default is None), help="GitHub Personal Access Token (classic or fine-grained with repo access)")
    parser.add_argument('--repo', default='nisar-pulse', help="Repository name (default: nisar-pulse)")
    parser.add_argument('--private', action='store_true', help="Make the repository private")
    parser.add_argument('--owner', default=None, help="Target owner/organization if different from token owner")
    args = parser.parse_args()

    upload_project(token=args.token, repo_name=args.repo, private=args.private, owner=args.owner)

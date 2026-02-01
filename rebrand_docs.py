import os

files_to_process = [
    "documentation/PROJECT_DATASET_MANAGER.md",
    "documentation/VISION_PROMPTING.md",
    "documentation/IMAGE_PREPROCESSING.md"
]

replacements = {
    "CaptionFoundry": "RuCaptioner",
    "Caption Foundry": "RuCaptioner",
    "captionfoundry": "rucaptioner" # Lowercase for module names/dirs
}

for file_path in files_to_process:
    if os.path.exists(file_path):
        print(f"Processing {file_path}...")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            for old, new in replacements.items():
                content = content.replace(old, new)
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"Updated {file_path}")
            else:
                print(f"No changes needed for {file_path}")
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    else:
        print(f"Skipping {file_path} (not found)")

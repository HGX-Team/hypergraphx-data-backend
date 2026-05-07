import os

def create_bib_files(root_dir: str):
    """
    Walk through all subdirectories of root_dir and create an empty .bib file
    named after each subdirectory if it doesn't already exist.
    """
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip the root directory itself
        if dirpath == root_dir:
            continue

        subdir_name = os.path.basename(dirpath)
        bib_file_path = os.path.join(dirpath, f"{subdir_name}.bib")

        if not os.path.exists(bib_file_path):
            # Create an empty .bib file
            with open(bib_file_path, "w", encoding="utf-8") as f:
                pass
            print(f"Created: {bib_file_path}")
        else:
            print(f"Already exists: {bib_file_path}")

if __name__ == "__main__":
    # Example usage
    # Replace this path with the directory you want to process
    directory = input("Enter the path to the main directory: ").strip()
    if os.path.isdir(directory):
        create_bib_files(directory)
    else:
        print("Invalid directory path.")

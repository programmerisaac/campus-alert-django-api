import os

def print_tree(startpath, prefix=""):
    files = sorted(os.listdir(startpath))
    files = [f for f in files if f != "__pycache__"]  # Skip __pycache__

    for index, name in enumerate(files):
        path = os.path.join(startpath, name)
        connector = "└── " if index == len(files) - 1 else "├── "
        print(prefix + connector + name)

        if os.path.isdir(path):
            extension = "    " if index == len(files) - 1 else "│   "
            print_tree(path, prefix + extension)

if __name__ == "__main__":
    root_dir = os.path.basename(os.getcwd())
    print(root_dir + "/")
    print_tree(".")




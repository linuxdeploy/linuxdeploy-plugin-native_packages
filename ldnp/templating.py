from jinja2 import Environment, FileSystemLoader
from pathlib import Path


templates_dir_path = Path(__file__).parent / "templates"

jinja_env = Environment(loader=FileSystemLoader(templates_dir_path))

from setuptools import setup, find_packages
from pathlib import Path

ROOT = Path(__file__).parent
long_description = (ROOT / "README.md").read_text(encoding="utf-8")

setup(
    name="kg-extractor",
    version="0.1.0a0",
    author="KpiFinity",
    author_email="hello@kpifinity.com",
    description=(
        "Extract compliance rules from regulatory documents using "
        "LLM-assisted parsing. Phase 1 (compilation) only — must not be "
        "used at SKI runtime."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/kpifinity/ski-framework",
    license="Apache-2.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Legal Industry",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.9",
    install_requires=[
        "pydantic==2.6.3",
        "python-dotenv==1.0.1",
        "click==8.1.7",
        "pyyaml==6.0.1",
        "httpx==0.27.0",
        "pypdf==4.2.0",
        "python-docx==1.1.0",
        "anthropic==0.104.0",
        "openai==1.16.2",
    ],
    entry_points={
        "console_scripts": [
            "kg-extractor=kg_extractor.cli:main",
        ],
    },
)

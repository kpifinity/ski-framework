from setuptools import setup, find_packages
from pathlib import Path

ROOT = Path(__file__).parent
long_description = (ROOT / "README.md").read_text(encoding="utf-8")

setup(
    name="kg-validator",
    version="0.1.0a0",
    author="KpiFinity",
    author_email="hello@kpifinity.com",
    description="Validate and review extracted compliance rules with mandatory human expert oversight.",
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
        "pydantic==2.13.4",
        "click==8.1.8",
        "python-dotenv==1.2.1",
        "rapidfuzz==3.13.0",
        "jinja2==3.1.6",
    ],
    entry_points={
        "console_scripts": [
            "kg-validator=kg_validator.cli:main",
        ],
    },
)

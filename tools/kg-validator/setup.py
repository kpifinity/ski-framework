from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="kg-validator",
    version="1.0.0",
    author="KpiFinity",
    author_email="hello@kpifinity.com",
    description="Validate and review extracted compliance rules with human expert oversight",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/kpifinity/ski-framework",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.9",
    install_requires=[
        "pydantic>=2.0.0",
        "click>=8.1.0",
        "python-dotenv>=1.0.0",
        "rapidfuzz>=3.0.0",
        "jinja2>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "kg-validator=kg_validator.cli:main",
        ],
    },
)

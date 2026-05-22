from setuptools import setup, find_packages
from pathlib import Path

ROOT = Path(__file__).parent
long_description = "Audit ledger management tool for the SKI Framework."

setup(
    name="audit-ledger",
    version="0.1.0a0",
    author="KpiFinity",
    author_email="hello@kpifinity.com",
    description=long_description,
    license="Apache-2.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=[
        "psycopg[binary]==3.1.18",
        "sqlalchemy==2.0.27",
        "click==8.1.7",
        "pydantic==2.6.3",
        "python-dotenv==1.0.1",
        "jinja2==3.1.3",
        "pyyaml==6.0.1",
        "httpx==0.28.1",
        "tabulate==0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "audit-ledger=audit_ledger.cli:main",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)

from setuptools import setup, find_packages
from pathlib import Path

ROOT = Path(__file__).parent
long_description = (ROOT / "README.md").read_text(encoding="utf-8")

setup(
    name="ski-model-deploy",
    version="0.1.0a0",
    author="KpiFinity",
    author_email="hello@kpifinity.com",
    description="Deploy and verify signed Knowledge Graphs against a SKI Model runtime.",
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
        "Intended Audience :: System Administrators",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.9",
    install_requires=[
        "click==8.1.7",
        "pydantic==2.6.3",
        "python-dotenv==1.0.1",
        "pyyaml==6.0.1",
        "jinja2==3.1.3",
        "httpx==0.27.0",
        "cryptography==42.0.5",
        "docker==7.0.0",
        "psycopg[binary]==3.1.18",
    ],
    entry_points={
        "console_scripts": [
            "ski-model-deploy=ski_model_deploy.cli:main",
        ],
    },
)

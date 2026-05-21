from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="milm-deploy",
    version="1.0.0",
    author="KpiFinity",
    author_email="hello@kpifinity.com",
    description="Deploy and configure the MiLM inference engine on-premise",
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
        "click>=8.1.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
        "pyyaml>=6.0.0",
        "jinja2>=3.1.0",
        "requests>=2.31.0",
        "docker>=6.0.0",
        "kubernetes>=25.0.0",
        "psycopg2-binary>=2.9.0",
    ],
    entry_points={
        "console_scripts": [
            "milm-deploy=milm_deploy.cli:main",
        ],
    },
)

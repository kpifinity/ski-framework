from setuptools import setup, find_packages

setup(
    name="audit-ledger",
    version="1.0.0",
    description="Audit Ledger Management Tool for SKI Framework",
    author="SKI Framework Contributors",
    license="CC BY 4.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=[
        "psycopg2-binary>=2.9.0",
        "sqlalchemy>=2.0.0",
        "click>=8.1.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
        "jinja2>=3.1.0",
        "pyyaml>=6.0.0",
        "requests>=2.31.0",
        "tabulate>=0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "audit-ledger=audit_ledger.cli:main",
        ],
    },
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: Other/Proprietary License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)

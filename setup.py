from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="protolink",
    version="0.1.0",
    author="Nikolaos Maroulis",
    author_email="nikolaos@maroulis.dev",
    description="A framework for building and managing agents based on the A2A protocol.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nMaroulis/protolink",
    packages=find_packages(where="protolink"),
    package_dir={"": "protolink"},
    python_requires=">=3.8",
    install_requires=[],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
)

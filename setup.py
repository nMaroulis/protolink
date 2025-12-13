from setuptools import find_packages, setup

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()

# Dependencies
test_deps = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-mock>=3.10.0",
]

# Optional dependency groups
extra_deps = {
    "http": [
        "httpx>=0.24.0",
        "starlette>=0.49.3",
        "uvicorn>=0.38.0",
        "websockets>=15.0",
    ],
    "llms": [
        "openai>=1.0.0",
        "llama-cpp-python>=0.2.0",
        "anthropic>=0.7.0",
    ],
    # All optional dependencies
    "all": [
        "httpx>=0.24.0",
        "starlette>=0.49.3",
        "uvicorn>=0.38.0",
        "websockets>=15.0",
        "openai>=1.0.0",
        "llama-cpp-python>=0.2.0",
        "anthropic>=0.7.0",
    ],
}

setup(
    name="protolink",
    version="0.4.0",
    author="Nikolaos Maroulis",
    author_email="nikolaos@maroulis.dev",
    description="A framework for building and managing agents based on the A2A protocol.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nMaroulis/protolink",
    packages=find_packages(where="."),
    package_dir={"": "."},
    python_requires=">=3.10",
    install_requires=[],
    extras_require={
        "test": test_deps,
        **extra_deps,
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    ],
)

from setuptools import setup

setup(
    name="stellar-appliance-cli",
    version="0.1.0",
    py_modules=["appliance_cli"],
    entry_points={
        "console_scripts": [
            "aella_cli=appliance_cli:main",
        ],
    },
    install_requires=[],
    python_requires=">=3.8",
)

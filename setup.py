from os import path
from setuptools import setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the relevant file
with open(path.join(here, 'README.md'), 'r') as f:
    long_description = f.read()

# Get version from file
with open(path.join(here, 'version'), 'r') as f:
    version = f.read().strip()

setup(
    name='youtrack',
    version=version,
    python_requires='>3',
    packages=['youtrack', 'youtrack.sync'],
    url='https://github.com/JetBrains/youtrack-rest-python-library',
    include_package_data=True,
    license='Apache 2.0',
    maintainer='Alexander Buturlinov',
    maintainer_email='imboot85@gmail.com',
    description='Python library for interacting with YouTrack via REST API supporting python3',
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=[
        'httplib2 >= 0.7.4',
        'six'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent"
    ],
)

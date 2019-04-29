from os import path
from setuptools import setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the relevant file
with open(path.join(here, 'README.md')) as f:
    long_description = f.read()

setup(
    name='youtrack',
    version='0.1.0',
    python_requires='>3',
    packages=['youtrack', 'youtrack.sync'],
    url='https://github.com/8032/youtrack-rest-python-library',
    license='Apache 2.0',
    maintainer='Greg',
    maintainer_email='23417426+8032@users.noreply.github.com',
    description='Python library for interacting with YouTrack via REST API, ported from JetBrains python2 to python3',
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=[
        'httplib2 >= 0.7.4',
        'six'
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "INTENDED AUDIENCE :: DEVELOPERS",
    ],
)

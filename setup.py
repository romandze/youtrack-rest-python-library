from os import path
from setuptools import setup

here = path.abspath(path.dirname(__file__))

# Try to convert markdown readme file to rst format
try:
    import pypandoc
    md_file = path.join(here, 'README.md')
    rst_file = path.join(here, 'README.rst')
    pypandoc.convert_file(source_file=md_file, outputfile=rst_file, to='rst')
except (ImportError, OSError, IOError, RuntimeError):
    pass

# Get the long description from the relevant file
with open(path.join(here, 'README.rst')) as f:
    long_description = f.read()

# Get version from file
#with open(path.join(here, 'version')) as f:
#    version = f.read().strip()


setup(
    name='youtrack',
    version='0.1.0',
    python_requires='>3',
    packages=['youtrack', 'youtrack.sync'],
    url='https://github.com/JetBrains/youtrack-rest-python-library',
    license='Apache 2.0',
    maintainer='Greg',
    maintainer_email='23417426+8032@users.noreply.github.com',
    description='Python library for interacting with YouTrack via REST API, ported from JetBrains python2 to python3',
    long_description=long_description,
    install_requires=[
        'httplib2 >= 0.7.4',
        'six'
    ]
)

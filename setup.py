#!/usr/bin/env python
# coding=utf8

from distutils.core import setup

setup(name='wsgicgi',
      version='0.1',
      description='A WSGI wrapper around CGI scripts that allows running legacy CGI applications as WSGI apps. Initially created for running GNU mailman <= 2.1.',
      author='Marc Brinkmann',
      author_email='git@marcbrinkmann.de',
      url='http://github.com/mbr/wsgi-cgi',
      py_modules = ['wsgicgi'],
     )

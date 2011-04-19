#!/usr/bin/env python
# coding=utf8

import os
import re
from select import select
import subprocess
try:
	from cStringIO import StringIO
except ImportError:
	from StringIO import StringIO

class CGIAppException(Exception):
	pass

class CGIApp(object):
	server_msg = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
	<HTML>
	<HEAD>
	<TITLE>%(code)d - %(title)s</TITLE>
	</HEAD>
	<BODY>
	<H1>%(code)d %(title)s</H1>
	<P>%(message)s</P>
	<HR>
	<ADDRESS>wsgicgi.py</ADDRESS>
	</BODY>
	</HTML>
	"""
	response_re = re.compile(r'^(.*?)(?:\n|\r\n){2}(.*)', re.DOTALL)
	status_re = re.compile(r'(\d\d\d)\s(.*)')

	def __init__(self, basepath, cgi_handlers = {}, bufsize = -1, input_buf_size = 4096, output_buf_size = 4096, enable_script_filename = True):
		self.basepath = basepath
		self.bufsize = bufsize
		self.input_buf_size = input_buf_size
		self.output_buf_size = output_buf_size
		self.cgi_handlers = cgi_handlers
		self.enable_script_filename = enable_script_filename

	def __call__(self, environ, start_response):
		try:
			path_components = environ['PATH_INFO'].split('/')

			# "failsafe"
			path_info = ''
			script_path = os.path.abspath(os.path.join(self.basepath, *path_components))

			# try subpaths
			script_path_components = []
			while path_components:
				script_path_components.append(path_components.pop(0))

				candidate = os.path.join(self.basepath, *script_path_components)
				if os.path.exists(candidate) and not os.path.isdir(candidate):
					if path_components:
						path_info = '/' + '/'.join(path_components)
					script_path = os.path.abspath(os.path.join(self.basepath, *script_path_components))

			# no script? send 404
			if not os.path.exists(script_path):
				return self.send_message(environ, start_response, {
					'code': 404,
					'title': 'Not Found',
					'message': 'The requested URL %s was not found on this server.' % environ['PATH_INFO'],
				})
			elif os.path.isdir(script_path):
				return self.send_message(environ, start_response, {
					'code': 403,
					'title': 'Forbidden',
					'message': 'Directory access forbidden.',
				})

			# we ignore 5. from the CGI draft ("The CGI Script Command Line"),
			# as it is optional, and most scripts can handle it themselves
			#if environ['REQUEST_METHOD'].upper() in ('GET','HEAD'):
				# pass # handle arguments here

			# construct CGI environment
			cgienv = {
				# these are the required variables
				'AUTH_TYPE': '', # unsupported
				'CONTENT_LENGTH': environ.get('CONTENT_LENGTH', ''),
				'CONTENT_TYPE': environ.get('CONTENT_TYPE', ''),
				'GATEWAY_INTERFACE': 'CGI/1.1',
				'PATH_INFO': path_info,
				'PATH_TRANSLATED': os.path.join(script_path), # partially supported
				'QUERY_STRING': environ.get('QUERY_STRING', ''),
				'REMOTE_ADDR': environ.get('REMOTE_ADDR', ''),
				'REMOTE_HOST': environ.get('REMOTE_HOST', ''),
				'REMOTE_IDENT': '', # unsupported
				'REMOTE_USER': '', # unsupported (related to AUTH_TYPE)
				'REQUEST_METHOD': environ.get('REQUEST_METHOD', ''),
				'SCRIPT_NAME': environ.get('SCRIPT_NAME', ''),
				'SERVER_NAME': environ.get('SERVER_NAME', ''),
				'SERVER_PORT': environ.get('SERVER_PORT', ''),
				'SERVER_PROTOCOL': environ.get('SERVER_PROTOCOL', '') ,
				'SERVER_SOFTWARE': environ.get('SERVER_SOFTWARE', ''),
			}

			if self.enable_script_filename:
				cgienv['SCRIPT_FILENAME'] = script_path
			for name in environ:
				if name.startswith('HTTP_'):
					cgienv[name] = environ[name]

			# open script
			base, ext = os.path.splitext(script_path)
			args = [script_path] if not ext in self.cgi_handlers else [self.cgi_handlers[ext], script_path]
			cgiscript = subprocess.Popen(
				args,
				bufsize = self.bufsize,
				stdin = subprocess.PIPE,
				stdout = subprocess.PIPE,
				stderr = environ['wsgi.errors'],
				cwd = '/',
				env = cgienv
			)

			# NOTE: it is tempting to simply pass environ['wsgi.input'] as stdout,
			#       however this falls apart once subprocess tries to access its fileno()

			# simply stuff everything into the pipe
			# FIXME: this could possibly break scripts that expect to be able to send data
			#        before having received the request
			data_left = int(environ.get('CONTENT_LENGTH', 0) or 0)
			while data_left:
				amount = min(self.input_buf_size, data_left)
				data = environ['wsgi.input'].read(amount)
				data_left -= len(data)
				cgiscript.stdin.write(data)
			cgiscript.stdin.close()

			# get the header portion
			data = ''
			buf = StringIO()
			while -1 == buf.getvalue().rfind('\n\n') and -1 == buf.getvalue().rfind('\r\n\r\n'):
				data = cgiscript.stdout.read(512)
				if '' == data:
					raise CGIAppException('CGI script did not return a valid header.')
				buf.write(data)

			m = self.response_re.match(buf.getvalue())
			remainder = m.group(2)
			# process headers
			headers = {}
			for h in m.group(1).splitlines():
				name, val = h.split(':', 1)
				headers[name] = val.lstrip()


			status = 200
			phrase = 'OK'
			if 'Location' in headers:
				status = 302
				phrase = 'redirect'
				# Location simply passed through

			if 'Status' in headers:
				m = self.status_re.match(headers['Status'])
				status, phrase = int(m.group(1)), m.group(2)

				del headers['Status']

			# serve
			start_response('%03d %s' % (status, phrase), headers.items())

			def serve_response():
				yield remainder
				while True:
					data = cgiscript.stdout.read(self.output_buf_size)
					if '' == data: break
					yield data

			return serve_response()
		except (OSError, CGIAppException), e:
			return self.send_message(environ, start_response, {
				'code': 500,
				'title': 'Internal Server Error',
				'message': '%s' % e,
			})

	def send_message(self, environ, start_response, data):
		start_response('%d %s' % (data['code'], data['title'].upper()), [('Content-type', 'text/html; charset=iso-8859-1')])
		return [self.server_msg % data]

if '__main__' == __name__:
	from wsgiref.simple_server import make_server

	app = CGIApp('./cgi-bin', cgi_handlers = {
		'.php': '/usr/bin/php-cgi',
	})
	server = make_server('0.0.0.0', 12345, app)
	server.serve_forever()

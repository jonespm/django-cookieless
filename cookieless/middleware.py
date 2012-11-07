#-*- coding:utf-8 -*-import time
import re, pdb, time

from django.conf import settings
from django.utils.cache import patch_vary_headers
from django.utils.http import cookie_date
from django.utils.importlib import import_module
from django.http  import  HttpResponseRedirect
from django.contrib.sessions.middleware import SessionMiddleware
# Obscure the session id when passing it around in HTML
from cookieless.utils import CryptSession
from cookieless.config import LINKS_RE, DEFAULT_SETTINGS

class CookielessSessionMiddleware(object):
    """ Django snippets julio carlos and Ivscar 
        http://djangosnippets.org/snippets/1540/
        Plus django.session.middleware combined

        Install by replacing 
        'django.contrib.sessions.middleware.SessionMiddleware'
        with 'cookieless.middleware.CookielessSessionMiddleware'

        NB: Remember only decorated methods are cookieless
    """

    def __init__(self):
        """ Add regex for auto inserts and an instance of
            the standard django.contrib.sessions middleware
        """
        self.settings = getattr(settings, 'COOKIELESS', DEFAULT_SETTINGS)
        self._re_links = re.compile(LINKS_RE, re.I)
        self._re_forms = re.compile('</form>', re.I)
        self._sesh = CryptSession()
        self.standard_session = SessionMiddleware()
        self.engine = import_module(settings.SESSION_ENGINE)


    def process_request(self, request):
        """ Check if we have the session key from a cookie, 
            if not check post, and get if allowed
            If decryption fails 
            (ie secret is wrong because of other setting restrictions)
            decrypt may not return a real key so
            test for that and start a new session if so
            NB: Cant check for no_cookies attribute of request here since 
                its before it gets sent to the view
        """
        name = settings.SESSION_COOKIE_NAME
        session_key = self._sesh.decrypt(request, 
                                         request.POST.get(name, None))
        if not session_key and self.settings.get('USE_GET', False):
            session_key = self._sesh.decrypt(request, 
                                             request.GET.get(name, ''))
        if not session_key:
            session_key = request.COOKIES.get(name, '')

        try:
            request.session = self.engine.SessionStore(session_key)
        except:
            pass
        # NB: engine may work but return empty key less session
        try:
            session_key = request.session.session_key
        except:
            session_key = ''
        # If the session_key isn't tied to a session - create a new one
        if not session_key:
            request.session = self.engine.SessionStore() 
            request.session.save()

    def process_response(self, request, response):
        """
        Copied from contrib.session.middleware with no_cookies switch added ...
        If request.session was modified, or if the configuration is to save the
        session every time, save the changes and set a session cookie.
        NB: request.COOKIES are the sent ones and response.cookies the set ones!
        """
        if getattr(request, 'no_cookies', False):
            # The django test client has mock session / cookies which assume cookies are in use
            # so to turn off cookieless for tests 
            # TODO: Find work around for test browser switch hardcoded to session being from django.contrib.session 
            if request.META.get('SERVER_NAME', '') == 'testserver':
                return self.standard_session.process_response(request, response)
            
            if request.COOKIES:
                if self.settings.get('NO_COOKIE_PERSIST', False):
                    # Don't persist a session with cookieless for any session 
                    # thats been set against a cookie 
                    # - may be attached to a user - so always start a new separate one
                    cookie_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME, '')
                    if cookie_key == request.session.session_key:
                        request.session = self.engine.SessionStore() 
                        request.session.save()

                # Blat any existing cookies
                for key in request.COOKIES.keys():
                    response.delete_cookie(key)

            # Dont set any new cookies
            response.cookies.clear()

            # cookieless - do same as standard process response
            #              but dont set the cookie
            if self.settings.get('REWRITE', False):
                response = self.nocookies_response(request, response)

            try:
                accessed = request.session.accessed
                modified = request.session.modified
            except AttributeError:
                pass
            else:
                if modified or settings.SESSION_SAVE_EVERY_REQUEST:
                    if request.session.get_expire_at_browser_close():
                        max_age = None
                        expires = None
                    else:
                        max_age = request.session.get_expiry_age()
                        expires_time = time.time() + max_age
                        expires = cookie_date(expires_time)
                # Save the session data and refresh the client cookie.
                request.session.save()
            return response
        else:
            return self.standard_session.process_response(request, response)

    def nocookies_response(self, request, response):
        """ Option to rewrite forms and urls to add session automatically """
        name = settings.SESSION_COOKIE_NAME
        session_key = ''
        if request.session.session_key and not request.path.startswith("/admin"):  
            session_key = self._sesh.encrypt(request, request.session.session_key) 

            if type(response) is HttpResponseRedirect:
                if not session_key: 
                    session_key = ""
                redirect_url = [x[1] for x in response.items() if x[0] == "Location"][0]
                redirect_url = self._sesh.prepare_url(redirect_url)
                return HttpResponseRedirect('%s%s=%s' % (redirect_url, name, 
                                                         session_key)) 


            def new_url(m):
                anchor_value = ""
                if m.groupdict().get("anchor"): 
                    anchor_value = m.groupdict().get("anchor")
                return_str = '<a%shref="%s%s=%s%s"%s>' % (
                                 m.groupdict()['pre_href'],
                                 self._sesh.prepare_url(m.groupdict()['in_href']),
                                 name,
                                 session_key,
                                 anchor_value,
                                 m.groupdict()['post_href']
                                 )
                return return_str                                 

            if self.settings.get('USE_GET', False):            
                try:
                    response.content = self._re_links.sub(new_url, response.content)
                except:
                    pass

            repl_form = '''<div><input type="hidden" name="%s" value="%s" />
                           </div></form>'''
            repl_form = repl_form % (name, session_key)

            try:
                response.content = self._re_forms.sub(repl_form, response.content)
            except:
                pass
            return response
        else:
            return response        






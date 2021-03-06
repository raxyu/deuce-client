"""
Deuce Authentication API
"""
import json
import requests
import logging
import datetime
import time

from deuce.common.command import Command


# TODO: Add a base Auth class
# TODO: Convert below to use KeystoneClient

class AuthenticationError(Exception):
    pass


class AuthCredentialsErrors(AuthenticationError):
    pass


class AuthExpirationError(AuthenticationError):
    pass


class Authentication(Command):
    """
    Username+ApiKey Authentication for an HTTP REST API
    Presently supports the RAX v2.0 API
    """

    @staticmethod
    def __get_identity_apihost(datacenter):
        if datacenter in ('us', 'uk', 'lon', 'iad', 'dfw', 'ord'):
            return 'identity.api.rackspacecloud.com'
        elif datacenter in ('hkg', 'syd'):
            return'{0:}.identity.api.rackspacecloud.com'.format(datacenter)
        else:
            raise AuthenticationError(
                'Unknown Data Center: {0:}'.format(datacenter))

    def __init__(self, userid, credentials, usertype='user', method='apikey',
                 datacenter='us'):
        """
        Initialize the Agent access
          sslenabled - True if using HTTPS; otherwise False
          authenticator - instance of deuceclient.auth.Authentication to use
          apihost - server to use for API calls
          method - type of credentials being provided
                   (apikey, password, token)
                   ** all lower case **
          usertype - type of userid being provided
                     (username, tenantid, tenantname)
                     ** all lower case **
          userid - username/tenantid/tenantname for the authentication
          credentials - apikey/password/token for the given user
        """
        apihost = Authentication.__get_identity_apihost(datacenter)
        super(self.__class__, self).__init__(True, apihost, "/v2.0/tokens")

        self.log = logging.getLogger(__name__)
        self.parameters = {}
        self.parameters['userid'] = userid
        self.parameters['credentials'] = credentials
        self.parameters['usertype'] = usertype
        self.parameters['method'] = method
        self.parameters['datacenter'] = datacenter
        self.parameters['apihost'] = apihost

        self.o = {}
        self.o['auth'] = {}
        if method == 'apikey':
            self.log.debug('Authenticating with APIKEY...')
            if usertype == 'user':
                self.log.debug('Authenticating with user...')
                rax_api_keyspace = 'RAX-KSKEY:apiKeyCredentials'
                self.o['auth'][rax_api_keyspace] = {}
                self.o['auth'][rax_api_keyspace]['username'] = userid
                self.o['auth'][rax_api_keyspace]['apiKey'] = credentials

            elif usertype == 'tenantid':
                self.log.debug('Authenticating with tentantid...')
                self.o['auth']['tenantId'] = userid
                self.o['auth']['token'] = {}
                self.o['auth']['token']['id'] = credentials

            else:
                raise AuthCredentialsErrors(
                    'Unknown userid type ({0:}) for authentication '
                    'method ({1:})'.format(usertype, method))

        elif method == 'password':
            self.log.debug('Authenticating with Password...')
            if usertype == 'user':
                self.log.debug('Authenticating with user...')
                self.o['auth']['passwordCredentials'] = {}
                self.o['auth']['passwordCredentials']['username'] = userid
                self.o['auth']['passwordCredentials']['password'] = credentials

            elif usertype == 'tenantid':
                self.log.debug('Authenticating with tentantid...')
                self.o['auth']['tenantId'] = userid
                self.o['auth']['token'] = {}
                self.o['auth']['token']['id'] = credentials

            else:
                raise AuthCredentialsErrors(
                    'Unknown userid type ({0:}) for authentication '
                    'method ({1:})'.format(usertype, method))

        elif method == 'token':
            self.log.debug('Authenticating with Token...')
            if usertype == 'tenantid':
                self.log.debug('Authenticating with tentantid...')
                self.o['auth']['tenantId'] = userid
                self.o['auth']['token'] = {}
                self.o['auth']['token']['id'] = credentials

            elif usertype == 'tenantname':
                self.log.debug('Authenticating with tentant name...')
                self.o['auth']['tenantName'] = userid
                self.o['auth']['token'] = {}
                self.o['auth']['token']['id'] = credentials

            else:
                raise AuthCredentialsErrors(
                    'Unknown userid type ({0:}) for authentication '
                    'method ({1:})'.format(usertype, method))

        elif method == 'validate':
            self.log.debug('Authenticating for Validation...')
            self.o['auth']['token'] = {}
            self.o['auth']['token']['id'] = credentials

        self.body = json.dumps(self.o)
        self.auth_data = {}

    def GetToken(self, retry=5):
        """
        Retrieve the Authentication Tokey

        Note: This may expire quickly. Tokens are valid for 6 hours
              but are not instance specific
        """
        self.log.debug('host: %s', self.apihost)
        self.log.debug('body: %s', self.Body)
        self.log.debug('headers: %s', self.Headers)
        self.log.debug('uri: %s', self.Uri)
        response = requests.post(self.Uri,
                                 headers=self.Headers,
                                 data=self.Body)
        if response.status_code is 200:
            self.auth_data = response.json()
            self.log.info('auth token: %s',
                          self.auth_data['access']['token']['id'])
            self.log.debug('GetToken Response: {0:}'.format(self.auth_data))
            return self.auth_data['access']['token']['id']
        elif response.status_code is 404:
            self.log.error('server return unavailable. Trying again up to '
                           '{0:} times.'.format(retry))
            self.log.error('reason: ' + response.reason)
            if retry is 0:
                self.log.error('No more retries. Failed.')
                raise AuthenticationError(
                    'No more retries for authentication.')
            else:
                return self.GetToken(retry - 1)
        elif response.status_code >= 400:
            self.log.error('reason: ' + response.reason)
            self.log.error('failed to authenticate - {0:}: {1:}'.format(
                response.status_code, response.text))
        else:
            self.log.error('reason: ' + response.reason)
            self.log.error('failed to authenticate: ' + response.text)
            self.auth_data = {}
            return ''

    def IsExpired(self, fuzz=0):
        """
        Checks to see if the auth token has expired by comparing its
        expiration time stamp to the current time in utc
        """
        def time_fuzzy_compare(timeval_older, timeval_newer, new_fuzz):
            """
            (internal) Fuzzy Compare two time values
            """

            def time_layer_compare(val_older, val_newer, next_layer):
                """
                (internal) compare layers recursively
                """
                if val_older == val_newer:
                    if next_layer is not None:
                        return next_layer['call'](next_layer['older'],
                                                  next_layer['newer'],
                                                  next_layer['next'])
                    else:
                        return True
                else:
                    return val_older > val_newer

            time_layers = {
                'call': time_layer_compare,
                'older': timeval_older.month,
                'newer': timeval_newer.month,
                'next': {
                    'call': time_layer_compare,
                    'older': timeval_older.day,
                    'newer': timeval_newer.day,
                    'next': {
                        'call': time_layer_compare,
                        'older': timeval_older.hour,
                        'newer': timeval_newer.hour,
                        'next': {
                            'call': time_layer_compare,
                            'older': timeval_older.minute,
                            'newer': timeval_newer.minute,
                            'next': {
                                'call': time_layer_compare,
                                'older': timeval_older.second,
                                'newer': (timeval_newer.second + new_fuzz),
                                'next': None
                            }
                        }
                    }
                }
            }

            return time_layer_compare(timeval_older.year,
                                      timeval_newer.year,
                                      time_layers)

        # 2013-12-24T14:02:26.550Z
        expirationtime = datetime.datetime.utcnow()
        try:
            try:
                expirationtime = datetime.datetime.strptime(
                    self.AuthExpirationTime, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                try:
                    expirationtime = datetime.datetime.strptime(
                        self.AuthExpirationTime, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    msg = 'Unknown time format: {1:}'.format(
                        self.AuthExpirationTime)
                    self.log.error(msg)
                    raise AuthenticationError(msg)
        except AuthExpirationError:
            self.log.debug('Not Auth Token data to check against.')
            return True

        nowtime = datetime.datetime.utcnow()

        # Log the times and then do a fuzzy comparison
        self.log.debug('Current Time: ' + str(nowtime))
        self.log.debug('Auth Token Expiration Time: ' + str(expirationtime))
        if time_fuzzy_compare(expirationtime, nowtime, fuzz):
            self.log.debug(
                'Auth Token is still valid (fuzz = {0:} seconds)'.format(fuzz))
            return False
        else:
            self.log.debug(
                'Auth Token is expired (fuzz = {0:} seconds)'.format(fuzz))
            return True

    @property
    def AuthToken(self):
        """
        Retrieve the cached Authentication Token

        Note: See GetToken()
        """
        try:
            if self.IsExpired():
                # Obviously expired
                return self.GetToken()
            elif self.IsExpired(fuzz=2):
                # Near expiration
                self.log.info(
                    'Token about to expire. Waiting 3 seconds to renew')
                time.sleep(3)
                return self.GetToken()
            else:
                return self.auth_data['access']['token']['id']
        except LookupError:
            raise AuthCredentialsErrors(
                'Unable to retrieve authentication token')

    @property
    def AuthExpirationTime(self):
        """
        Retrieve the date-time for when the AuthToken expires
        """
        try:
            return self.auth_data['access']['token']['expires']
        except LookupError:
            raise AuthExpirationError(
                'AuthToken Expiration Time Not available.')

    @property
    def AuthTenantId(self):
        """
        Retrieve the User Account Identifier
        """
        try:
            return self.auth_data['access']['token']['tenant']['id']
        except LookupError:
            self.log.error('Unable to retrieve User Identifier. '
                           'Did you authenticate?')
            raise AuthenticationError('Unable to retrieve User Identifier. '
                                      'Did you authenticate?')

    @property
    def AuthTenantName(self):
        """
        Retrieve the User Account Identifier
        """
        try:
            return self.auth_data['access']['token']['tenant']['name']
        except LookupError:
            msg = 'Unable to retrieve User Identifier. Did you authenticate?'
            self.log.error(msg)
            raise AuthenticationError(msg)

    @property
    def AuthUserId(self):
        """
        Retrieve the User Account Identifier
        """
        try:
            return self.auth_data['access']['user']['id']
        except LookupError:
            msg = 'Unable to retrieve User Identifier. Did you authenticate?'
            self.log.error(msg)
            raise AuthenticationError(msg)

    @property
    def MossoId(self):
        """
        Retrieve the MossoId for the user

        Note: Assumes all DCs have the same mossoid
        """
        try:
            mossoid = None
            for service in self.auth_data['access']['serviceCatalog']:
                if service['name'] == 'cloudFiles':
                    for endpoint in service['endpoints']:
                        if len(endpoint['tenantId']):
                            mossoid = endpoint['tenantId']
                            break
            return mossoid
        except LookupError:
            msg = 'Unable to retrieve MossoID. Did you authenticate?'
            self.log.error(msg)
            raise AuthenticationError(msg)

    @property
    def AllCredentials(self, get_credentials=False):
        """
        Retrieve the various user's credential for different methods of auth

        get_credentials - whether or not to list or get the credentials

        Note: get_credentials is RAX specific
        """
        headers = self.Headers
        headers['X-Auth-Token'] = self.AuthToken
        old_uri = self.uri
        if not get_credentials:
            self.ReInit(True,
                        '/v2.0/users/{0:}/OS-KSADM/credentials'.format(
                            self.AuthUserId))
        else:
            self.ReInit(True,
                        '/v2.0/users/{0:}/OS-KSADM/credentials/'
                        'RAX-KSKEY:apiKeyCredentials'.format(
                            self.parameters['userid']))

        self.log.debug('host: %s', self.apihost)
        self.log.debug('body: %s', self.Body)
        self.log.debug('headers: %s', headers)
        self.log.debug('uri: %s', self.Uri)
        response = requests.get(self.Uri, headers=headers)

        self.log.debug('Response ({0:}): {1:}'.format(response.status_code,
                                                      response.text))
        if response.status_code in (200, 203):
            return response.json()
        elif response.status_code == 404:
            msg = 'User does not have admin rights for the account.'
            self.log.error(msg)
            raise AuthenticationError(msg)
        else:
            self.log.error('reason: {0:}'.format(response.reason))
            self.log.error('failed to authenticate - {0:}: {1:}'.format(
                response.status_code, response.text))
            raise AuthenticationError('Error ({0:}: {1:}'.format(
                response.status_code, response.text))

        self.uri = old_uri

    def GetCloudFilesDataCenters(self):
        """
        Retrieve the list of Data Centers for the authentication
        Returns an array of data centers
        """
        try:
            # We need the auth data so we must have an Auth Token
            token = self.AuthToken  # noqa
            dclist = []
            for service in self.auth_data['access']['serviceCatalog']:
                if service['name'] == 'cloudFiles':
                    for endpoint in service['endpoints']:
                        dclist.append(endpoint['region'])
            return dclist
        except LookupError:
            msg = 'Unable to retrieve list of DCs for the currently ' \
                  'authenticated user'
            self.log.error(msg)
            raise AuthenticationError(msg)

    def GetCloudFilesUri(self, dc):
        """
        Retrieve the CloudFiles URI for the given DC

        Returns an array of dictionaries containing 'name' and 'uri' pairs
        """
        try:
            # We need the auth data so we must have an Auth Token
            token = self.AuthToken  # noqa
            dcuri = []
            for service in self.auth_data['access']['serviceCatalog']:
                if service['name'] == 'cloudFiles':
                    for endpoint in service['endpoints']:
                        if endpoint['region'] == dc:
                            publicuri = {}
                            publicuri['name'] = 'public'
                            publicuri['uri'] = endpoint['publicURL']
                            dcuri.append(publicuri)
                            sneturi = {}
                            sneturi['name'] = 'snet'
                            sneturi['uri'] = endpoint['internalURL']
                            dcuri.append(sneturi)
            return dcuri
        except LookupError:
            msg = 'Unable to retrieve DC URI for the currently ' \
                  'authenticated user'
            self.log.error(msg)
            raise AuthenticationError(msg)

    def GetCloudBackupApiUri(self, dc, useServiceNet=False):
        """
        Retrive the CloudBackup URI for a given DC.

        If possible, returns the Test API
        """
        dc = dc.upper()

        try:
            # We need the auth data so we must have an Auth Token
            token = self.AuthToken  # noqa
            dcuri = None

            for service in self.auth_data['access']['serviceCatalog']:
                if service['name'] == 'cloudBackup':
                    for endpoint in service['endpoints']:
                        if endpoint['region'] == dc:
                            if useServiceNet:
                                dcuri = endpoint['internalURL']
                            else:
                                dcuri = endpoint['publicURL']
            if dcuri is None:
                msg = 'Unable to find DC URI for the ' \
                      'currently authenticated user'
                self.log.error(msg)
                raise AuthenticationError(msg)
            else:
                return dcuri[len('https://'):].split('/')[0]

        except LookupError:
            msg = 'Unable to retrieve DC URI for the ' \
                  'currently authenticated user'
            self.log.error(msg)
            raise AuthenticationError(msg)

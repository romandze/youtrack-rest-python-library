import calendar
import functools
import httplib2
import json
import re
import sys
import tempfile
import time
import urllib.request, urllib.parse, urllib.error
from xml.dom import Node
from xml.dom import minidom
from xml.sax.saxutils import escape, quoteattr
import datetime
import youtrack

def relogin_on_401(f):
    @functools.wraps(f)
    def wrapped(self, *args, **kwargs):
        attempts = 10
        while attempts:
            try:
                return f(self, *args, **kwargs)
            except youtrack.YouTrackException as e:
                if e.response.status not in (401, 403, 500, 504):
                    raise e
                if e.response.status == 504:
                    time.sleep(30)
                elif self._last_credentials is not None:
                    self._login(*self._last_credentials)
                else:
                    break
                attempts -= 1
        return f(self, *args, **kwargs)
    return wrapped


class Connection(object):
    def __init__(self, url, login=None, password=None, proxy_info=None, token=None):
        if proxy_info is None:
            self.http = httplib2.Http(disable_ssl_certificate_validation=True)
        else:
            self.http = httplib2.Http(disable_ssl_certificate_validation=True,
                                      proxy_info=proxy_info)

        self.url = url.rstrip('/')
        self.baseUrl = self.url + "/rest"
        self.headers = dict()
        self._last_credentials = None

        if token:
            self.set_auth_token(token)
        elif login:
            self._login(login, password)

    def set_auth_token(self, token):
        if token:
            self.headers = {'Authorization': 'Bearer ' + token}

    def _login(self, login, password):
        if login is None:
            login = ''
        if password is None:
            password = ''
        body = 'login=%s&password=%s' % (urllib.parse.quote(login), urllib.parse.quote(password))
        response, content = self.http.request(
            uri=self.baseUrl + '/user/login',
            method='POST',
            body=body,
            headers={'Connection': 'keep-alive',
                     'Content-Type': 'application/x-www-form-urlencoded',
                     'Content-Length': str(len(body))}
        )
        if response.status != 200:
            raise youtrack.YouTrackException('/user/login', response, content)
        self.headers = {'Cookie': response['set-cookie'],
                        'Cache-Control': 'no-cache'}
        self._last_credentials = (login, password)

    @staticmethod
    def __get_illegal_xml_chars_re():
        _illegal_unichrs = [(0x00, 0x08), (0x0B, 0x0C), (0x0E, 0x1F),
                            (0x7F, 0x84), (0x86, 0x9F), (0xFDD0, 0xFDDF),
                            (0xFFFE, 0xFFFF)]
        _illegal_ranges = ["%s-%s" % (chr(low), chr(high))
                           for (low, high) in _illegal_unichrs]
        return re.compile(b'[%s]' % ''.join(_illegal_ranges))

    @relogin_on_401
    def _req(self, method, url, body=None, ignoreStatus=None, content_type=None):
        headers = self.headers
        if method == 'PUT' or method == 'POST':
            headers = headers.copy()
            if body:
                if content_type is None:
                    content_type = 'application/xml; charset=UTF-8'

                #if content_type.lower().find('/xml') != -1:
                    # Remove invalid xml/utf-8 data
                #    body = re.sub(self.__get_illegal_xml_chars_re(), b'', body)

                headers['Content-Type'] = content_type
                headers['Content-Length'] = len(body)
        elif method == 'GET' and content_type is not None:
            headers = headers.copy()
            headers['Accept'] = content_type

        if url.startswith('http'):
            response, content = self.http.request(
                url,
                method,
                headers=headers,
                body=body)
        else:
            response, content = self.http.request(
                (self.baseUrl + url),
                method,
                headers=headers,
                body=body)

        #if response.get('content-type', '').lower().find('/xml') != -1:
        #    # Remove invalid xml/utf-8 data
        #    content = re.sub(self.__get_illegal_xml_chars_re(), b'', content)

        # TODO: Why do we need this?
        #content = content.translate(None, '\0')
        content = re.sub(b'system_user[%@][a-zA-Z0-9]+', b'guest', content)

        if response.status not in (200, 201) and \
                (ignoreStatus != response.status):
            raise youtrack.YouTrackException(url, response, content)

        return response, content

    def _reqXml(self, method, url, body=None, ignoreStatus=None):
        response, content = self._req(
            method, url, body, ignoreStatus, "application/xml")
        if "content-type" in response:
            if response["content-type"].find("/xml") != -1 and content:
                try:
                    return minidom.parseString(content)
                except Exception as e:
                    print((str(e)))
                    return ""
            elif response["content-type"].find("/json") != -1 and content:
                try:
                    return json.loads(content)
                except Exception as e:
                    print((str(e)))
                    return ""

        if method == 'PUT' and ('location' in response):
            return 'Created: ' + response['location']
        else:
            return content

    def _getXml(self, url):
        response, content = self._req('GET', url)
        if content is None or content == '':
            raise youtrack.XmlException(url, response, content, 'Empty content')
        else:
            try:
                return minidom.parseString(content)
            except Exception as e:
                raise youtrack.XmlException(url, response, content, str(e))


    def _get(self, url):
        return self._reqXml('GET', url)

    def _put(self, url):
        return self._reqXml('PUT', url, '<empty/>\n\n')

    def getIssue(self, id):
        return youtrack.Issue(self._get("/issue/" + id), self)

    def createIssue(self, project, assignee, summary, description, priority=None, type=None, subsystem=None, state=None,
                    affectsVersion=None,
                    fixedVersion=None, fixedInBuild=None, permittedGroup=None):
        params = {'project': project,
                  'summary': summary}
        if description is not None:
            params['description'] = description
        if assignee is not None:
            params['assignee'] = assignee
        if priority is not None:
            params['priority'] = priority
        if type is not None:
            params['type'] = type
        if subsystem is not None:
            params['subsystem'] = subsystem
        if state is not None:
            params['state'] = state
        if affectsVersion is not None:
            params['affectsVersion'] = affectsVersion
        if fixedVersion is not None:
            params['fixVersion'] = fixedVersion
        if fixedInBuild is not None:
            params['fixedInBuild'] = fixedInBuild
        if permittedGroup is not None:
            params['permittedGroup'] = permittedGroup

        return self._req('PUT', '/issue', urllib.parse.urlencode(params), content_type='application/x-www-form-urlencoded')

    def deleteIssue(self, issue_id):
        return self._req('DELETE', '/issue/%s' % issue_id)

    def get_changes_for_issue(self, issue):
        return [youtrack.IssueChange(change, self) for change in
                self._get("/issue/%s/changes" % issue).getElementsByTagName('change')]

    def getComments(self, id):
        xml = self._getXml('/issue/' + id + '/comment')
        return [youtrack.Comment(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getAttachments(self, id):
        xml = self._getXml('/issue/' + id + '/attachment')
        return [youtrack.Attachment(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getAttachmentContent(self, url):
        f = urllib.request.urlopen(urllib.request.Request(self.url + url, headers=self.headers))
        return f

    def deleteAttachment(self, issue_id, attachment_id):
        return self._req('DELETE', '/issue/%s/attachment/%s' % (issue_id, attachment_id))

    def createAttachmentFromAttachment(self, issueId, a):
        try:
            content = a.getContent()
            contentLength = None
            if 'content-length' in content.headers.dict:
                contentLength = int(content.headers.dict['content-length'])
            print('Importing attachment for issue ', issueId)
            try:
                print('Name: ', a.name)
            except Exception as e:
                print(e)
            try:
                print('Author: ', a.authorLogin)
            except Exception as e:
                print(e)
            return self.importAttachment(issueId, a.name, content, a.authorLogin,
                contentLength=contentLength,
                contentType=content.info().type,
                created=a.created if hasattr(a, 'created') else None,
                group=a.group if hasattr(a, 'group') else '')
        except urllib.error.HTTPError as e:
            print("Can't create attachment")
            try:
                err_content = e.read()
                issue_id = issueId
                attach_name = a.name
                attach_url = a.url
                if isinstance(err_content, str):
                    err_content = err_content.encode('utf-8')
                if isinstance(issue_id, str):
                    issue_id = issue_id.encode('utf-8')
                if isinstance(attach_name, str):
                    attach_name = attach_name.encode('utf-8')
                if isinstance(attach_url, str):
                    attach_url = attach_url.encode('utf-8')
                print("HTTP CODE: ", e.code)
                print("REASON: ", err_content)
                print("IssueId: ", issue_id)
                print("Attachment filename: ", attach_name)
                print("Attachment URL: ", attach_url)
            except Exception:
                pass
        except Exception as e:
            try:
                print(content.geturl())
                print(content.getcode())
                print(content.info())
            except Exception:
                pass
            raise e
            

    def _process_attachments(self, authorLogin, content, contentLength, contentType, created, group, issueId, name,
                             url_prefix='/issue/'):
        if contentType is not None:
            content.contentType = contentType
        if contentLength is not None:
            content.contentLength = contentLength
        elif not isinstance(content, file):
            tmp = tempfile.NamedTemporaryFile(mode='w+b')
            tmp.write(content.read())
            tmp.flush()
            tmp.seek(0)
            content = tmp

        #post_data = {'attachment': content}
        post_data = {name: content}
        headers = self.headers.copy()
        #headers['Content-Type'] = contentType
        # name without extension to workaround: http://youtrack.jetbrains.net/issue/JT-6110
        params = {#'name': os.path.splitext(name)[0],
                  'authorLogin': authorLogin.encode('utf-8'),
        }
        if group is not None:
            params["group"] = group
        if created is not None:
            params['created'] = created
        else:
            try:
                params['created'] = self.getIssue(issueId).created
            except youtrack.YouTrackException:
                params['created'] = str(calendar.timegm(datetime.now().timetuple()) * 1000)

        url = self.baseUrl + url_prefix + issueId + "/attachment?" + urllib.parse.urlencode(params)
        r = urllib.request.Request(url,
            headers=headers, data=post_data)
        #r.set_proxy('localhost:8888', 'http')
        try:
            res = urllib.request.urlopen(r)
        except urllib.error.HTTPError as e:
            if e.code == 201:
                return e.msg + ' ' + name
            raise e
        return res

    def createAttachment(self, issueId, name, content, authorLogin='', contentType=None, contentLength=None,
                         created=None, group=''):
        return self._process_attachments(authorLogin, content, contentLength, contentType, created, group, issueId,
                                         name)

    def importAttachment(self, issue_id, name, content, authorLogin, contentType, contentLength, created=None,
                         group=''):
        return self._process_attachments(authorLogin, content, contentLength, contentType, created, group, issue_id,
                                         name, '/import/')


    def getLinks(self, id, outwardOnly=False):
        xml = self._getXml('/issue/' + urllib.parse.quote(id) + '/link')
        res = []
        for c in [e for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]:
            link = youtrack.Link(c, self)
            if link.source == id or not outwardOnly:
                res.append(link)
        return res

    def getUser(self, login):
        """ http://confluence.jetbrains.net/display/YTD2/GET+user
        """
        if login.startswith('system_user'):
            login = 'guest'
        return youtrack.User(self._get("/admin/user/" + urllib.parse.quote(login.encode('utf8'))), self)

    def createUser(self, user):
        """ user from getUser
        """
        # self.createUserDetailed(user.login, user.fullName, user.email, user.jabber)
        self.importUsers([user])

    def createUserDetailed(self, login, fullName, email, jabber):
        self.importUsers([{'login': login, 'fullName': fullName, 'email': email, 'jabber': jabber}])

    #        return self._put('/admin/user/' + login + '?' +
    #                         'password=' + password +
    #                         '&fullName=' + fullName +
    #                         '&email=' + email +
    #                         '&jabber=' + jabber)


    def importUsers(self, users):
        """ Import users, returns import result (http://confluence.jetbrains.net/display/YTD2/Import+Users)
            Example: importUsers([{'login':'vadim', 'fullName':'vadim', 'email':'eee@ss.com', 'jabber':'fff@fff.com'},
                                  {'login':'maxim', 'fullName':'maxim', 'email':'aaa@ss.com', 'jabber':'www@fff.com'}])
        """
        if len(users) <= 0: return

        known_attrs = ('login', 'fullName', 'email', 'jabber')

        xml = '<list>\n'
        for u in users:
            xml += '  <user ' + "".join(k + '=' + quoteattr(u[k]) + ' ' for k in u if k in known_attrs) + '/>\n'
        xml += '</list>'
        #TODO: convert response xml into python objects
        if isinstance(xml, str):
            xml = xml.encode('utf-8')
        return self._reqXml('PUT', '/import/users', xml, 400).toxml()

    def importIssuesXml(self, projectId, assigneeGroup, xml):
        return self._reqXml('PUT', '/import/' + urllib.parse.quote(projectId) + '/issues?' +
                                   urllib.parse.urlencode({'assigneeGroup': assigneeGroup}),
            xml, 400).toxml()

    def importLinks(self, links):
        """ Import links, returns import result (http://confluence.jetbrains.net/display/YTD2/Import+Links)
            Accepts result of getLinks()
            Example: importLinks([{'login':'vadim', 'fullName':'vadim', 'email':'eee@ss.com', 'jabber':'fff@fff.com'},
                                  {'login':'maxim', 'fullName':'maxim', 'email':'aaa@ss.com', 'jabber':'www@fff.com'}])
        """
        xml = '<list>\n'
        for l in links:
            # ignore typeOutward and typeInward returned by getLinks()
            xml += '  <link ' + "".join(attr + '=' + quoteattr(l[attr]) +
                                        ' ' for attr in l if attr not in ['typeInward', 'typeOutward']) + '/>\n'
        xml += '</list>'
        #TODO: convert response xml into python objects
        res = self._reqXml('PUT', '/import/links', xml, 400)
        return res.toxml() if hasattr(res, "toxml") else res

    def importIssues(self, projectId, assigneeGroup, issues):
        """ Import issues, returns import result (http://confluence.jetbrains.net/display/YTD2/Import+Issues)
            Accepts retrun of getIssues()
            Example: importIssues([{'numberInProject':'1', 'summary':'some problem', 'description':'some description', 'priority':'1',
                                    'fixedVersion':['1.0', '2.0'],
                                    'comment':[{'author':'yamaxim', 'text':'comment text', 'created':'1267030230127'}]},
                                   {'numberInProject':'2', 'summary':'some problem', 'description':'some description', 'priority':'1'}])
        """
        if len(issues) <= 0:
            return

        bad_fields = ['id', 'projectShortName', 'votes', 'commentsCount',
                      'historyUpdated', 'updatedByFullName', 'updaterFullName',
                      'reporterFullName', 'links', 'attachments', 'jiraId',
                      'entityId', 'tags', 'sprint', 'wikified']

        tt_settings = self.getProjectTimeTrackingSettings(projectId)
        if tt_settings and tt_settings.Enabled and tt_settings.TimeSpentField:
            bad_fields.append(tt_settings.TimeSpentField)

        if not self.isMarkdownSupported():
            bad_fields.append('markdown')

        xml = '<issues>\n'
        issue_records = dict([])

        for issue in issues:
            record = ""
            record += '  <issue>\n'

            comments = None
            if getattr(issue, "getComments", None):
                comments = issue.getComments()

            for issueAttr in issue:
                attrValue = issue[issueAttr]
                if attrValue is None:
                    continue
                if isinstance(attrValue, str):
                    attrValue = attrValue.encode('utf-8')
                if isinstance(issueAttr, str):
                    issueAttr = issueAttr.encode('utf-8')
                if issueAttr == 'comments':
                    comments = attrValue
                else:
                    # ignore bad fields from getIssue()
                    if issueAttr not in bad_fields:
                        record += '    <field name="' + issueAttr + '">\n'
                        if isinstance(attrValue, list) or getattr(attrValue, '__iter__', False):
                            for v in attrValue:
                                if isinstance(v, str):
                                    v = v.encode('utf-8')
                                record += '      <value>' + escape(v.strip()) + '</value>\n'
                        else:
                            record += '      <value>' + escape(attrValue.strip()) + '</value>\n'
                        record += '    </field>\n'

            if comments:
                for comment in comments:
                    record += '    <comment'
                    for ca in comment:
                        val = comment[ca]
                        if isinstance(ca, str):
                            ca = ca.encode('utf-8')
                        if isinstance(val, str):
                            val = val.encode('utf-8')
                        record += ' ' + ca + '=' + quoteattr(val, {"\n" : "&#xA;"})
                    record += '/>\n'

            record += '  </issue>\n'
            xml += record
            issue_records[issue.numberInProject] = record

        xml += '</issues>'

        #print xml
        #TODO: convert response xml into python objects

        if isinstance(xml, str):
            xml = xml.encode('utf-8')

        if isinstance(assigneeGroup, str):
            assigneeGroup = assigneeGroup.encode('utf-8')

        url = '/import/' + urllib.parse.quote(projectId) + '/issues?' + urllib.parse.urlencode({'assigneeGroup': assigneeGroup})
        if isinstance(url, str):
            url = url.encode('utf-8')
        result = self._reqXml('PUT', url, xml, 400)
        if (result == "") and (len(issues) > 1):
            for issue in issues:
                self.importIssues(projectId, assigneeGroup, [issue])
        response = ""
        try:
            response = result.toxml().encode('utf-8')
        except:
            sys.stderr.write("can't parse response")
            sys.stderr.write("request was")
            sys.stderr.write(xml)
            return response
        item_elements = minidom.parseString(response).getElementsByTagName("item")
        if len(item_elements) != len(issues):
            sys.stderr.write(response)
        else:
            for item in item_elements:
                id = item.attributes["id"].value
                imported = item.attributes["imported"].value.lower()
                if imported == "true":
                    print("Issue [ %s-%s ] imported successfully" % (projectId, id))
                else:
                    sys.stderr.write("")
                    sys.stderr.write("Failed to import issue [ %s-%s ]." % (projectId, id))
                    sys.stderr.write("Reason : ")
                    sys.stderr.write(item.toxml())
                    sys.stderr.write("Request was :")
                    if isinstance(issue_records[id], str):
                        sys.stderr.write(issue_records[id].encode('utf-8'))
                    else:
                        sys.stderr.write(issue_records[id])
                print("")
        return response

    def getProjects(self):
        projects = {}
        for e in self._get("/project/all").documentElement.childNodes:
            projects[e.getAttribute('shortName')] = e.getAttribute('name')
        return projects

    def getProject(self, projectId):
        """ http://confluence.jetbrains.net/display/YTD2/GET+project
        """
        return youtrack.Project(self._get("/admin/project/" + urllib.parse.quote(projectId)), self)

    def getProjectIds(self):
        xml = self._getXml('/admin/project/')
        return [e.getAttribute('id') for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getProjectAssigneeGroups(self, projectId):
        xml = self._getXml('/admin/project/' + urllib.parse.quote(projectId) + '/assignee/group')
        return [youtrack.Group(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getGroup(self, name):
        return youtrack.Group(self._get("/admin/group/" + urllib.parse.quote(name.encode('utf-8'))), self)

    def getGroups(self):
        xml = self._getXml('/admin/group')
        return [youtrack.Group(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def deleteGroup(self, name):
        return self._req('DELETE', "/admin/group/" + urllib.parse.quote(name.encode('utf-8')))

    def getUserGroups(self, userName):
        xml = self._getXml('/admin/user/%s/group' % urllib.parse.quote(userName.encode('utf-8')))
        return [youtrack.Group(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def setUserGroup(self, user_name, group_name):
        if isinstance(user_name, str):
            user_name = user_name.encode('utf-8')
        if isinstance(group_name, str):
            group_name = group_name.encode('utf-8')
        response, content = self._req('POST',
            '/admin/user/%s/group/%s' % (urllib.parse.quote(user_name), urllib.parse.quote(group_name)),
            body='')
        return response

    def createGroup(self, group):
        content = self._put(
            '/admin/group/%s?autoJoin=false' % urllib.parse.quote(group.name))
        return content

    def addUserRoleToGroup(self, group, userRole):
        url_group_name = urllib.parse.quote(group.name)
        url_role_name = urllib.parse.quote(userRole.name)
        response, content = self._req('PUT', '/admin/group/%s/role/%s' % (url_group_name, url_role_name),
            body=userRole.toXml())
        return content

    def getRole(self, name):
        return youtrack.Role(self._get("/admin/role/" + urllib.parse.quote(name)), self)

    def getRoles(self):
        xml = self._getXml('/admin/role')
        return [youtrack.Role(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getGroupRoles(self, group_name):
        xml = self._getXml('/admin/group/%s/role' % urllib.parse.quote(group_name))
        return [youtrack.UserRole(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def createRole(self, role):
        url_role_name = urllib.parse.quote(role.name)
        url_role_dscr = ''
        if hasattr(role, 'description'):
                url_role_dscr = urllib.parse.quote(role.description)
        content = self._put('/admin/role/%s?description=%s' % (url_role_name, url_role_dscr))
        return content

    def changeRole(self, role, new_name, new_description):
        url_role_name = urllib.parse.quote(role.name)
        url_new_name = urllib.parse.quote(new_name)
        url_new_dscr = urllib.parse.quote(new_description)
        content = self._req('POST',
            '/admin/role/%s?newName=%s&description=%s' % (url_role_name, url_new_name, url_new_dscr))
        return content

    def addPermissionToRole(self, role, permission):
        url_role_name = urllib.parse.quote(role.name)
        url_prm_name = urllib.parse.quote(permission.name)
        content = self._req('POST', '/admin/role/%s/permission/%s' % (url_role_name, url_prm_name))
        return content

    def getRolePermissions(self, role):
        xml = self._getXml('/admin/role/%s/permission' % urllib.parse.quote(role.name))
        return [youtrack.Permission(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getPermissions(self):
        xml = self._getXml('/admin/permission')
        return [youtrack.Permission(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getSubsystem(self, projectId, name):
        xml = self._getXml('/admin/project/' + projectId + '/subsystem/' + urllib.parse.quote(name))
        return youtrack.Subsystem(xml, self)

    def getSubsystems(self, projectId):
        xml = self._getXml('/admin/project/' + projectId + '/subsystem')
        return [youtrack.Subsystem(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getVersions(self, projectId):
        xml = self._getXml('/admin/project/' + urllib.parse.quote(projectId) + '/version?showReleased=true')
        return [self.getVersion(projectId, v.getAttribute('name')) for v in
                xml.documentElement.getElementsByTagName('version')]

    def getVersion(self, projectId, name):
        return youtrack.Version(
            self._get("/admin/project/" + urllib.parse.quote(projectId) + "/version/" + urllib.parse.quote(name)), self)

    def getBuilds(self, projectId):
        xml = self._getXml('/admin/project/' + urllib.parse.quote(projectId) + '/build')
        return [youtrack.Build(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]


    def getUsers(self, params={}):
        first = True
        users = []
        position = 0
        user_search_params = urllib.parse.urlencode(params)
        while True:
            xml = self._getXml("/admin/user/?start=%s&%s" % (str(position), user_search_params))
            position += 10
            newUsers = [youtrack.User(e, self) for e in xml.documentElement.childNodes if
                        e.nodeType == Node.ELEMENT_NODE]
            if not len(newUsers): return users
            users += newUsers


    def getUsersTen(self, start):
        xml = self._getXml("/admin/user/?start=%s" % str(start))
        users = [youtrack.User(e, self) for e in xml.documentElement.childNodes if
                 e.nodeType == Node.ELEMENT_NODE]
        return users

    def deleteUser(self, login):
        return self._req('DELETE', "/admin/user/" + urllib.parse.quote(login.encode('utf-8')))

    # TODO this function is deprecated
    def createBuild(self):
        raise NotImplementedError

    # TODO this function is deprecated
    def createBuilds(self):
        raise NotImplementedError

    def createProject(self, project):
        return self.createProjectDetailed(project.id, project.name, project.description, project.lead)

    def deleteProject(self, projectId):
        return self._req('DELETE', "/admin/project/" + urllib.parse.quote(projectId))

    def createProjectDetailed(self, projectId, name, description, projectLeadLogin, startingNumber=1):
        _name = name
        _desc = description
        if isinstance(_name, str):
            _name = _name.encode('utf-8')
        if isinstance(_desc, str):
            _desc = _desc.encode('utf-8')
        _name = _name.replace('/', ' ')
        return self._put('/admin/project/' + projectId + '?' +
                         urllib.parse.urlencode({'projectName': _name,
                                           'description': _desc + ' ',
                                           'projectLeadLogin': projectLeadLogin,
                                           'lead': projectLeadLogin,
                                           'startingNumber': str(startingNumber)}))

    # TODO this function is deprecated
    def createSubsystems(self, projectId, subsystems):
        """ Accepts result of getSubsystems()
        """

        for s in subsystems:
            self.createSubsystem(projectId, s)

    # TODO this function is deprecated
    def createSubsystem(self, projectId, s):
        return self.createSubsystemDetailed(projectId, s.name, s.isDefault,
            s.defaultAssignee if s.defaultAssignee != '<no user>' else '')

    # TODO this function is deprecated
    def createSubsystemDetailed(self, projectId, name, isDefault, defaultAssigneeLogin):
        self._put('/admin/project/' + projectId + '/subsystem/' + urllib.parse.quote(name.encode('utf-8')) + "?" +
                  urllib.parse.urlencode({'isDefault': str(isDefault),
                                    'defaultAssignee': defaultAssigneeLogin}))

        return 'Created'

    # TODO this function is deprecated
    def deleteSubsystem(self, projectId, name):
        return self._reqXml('DELETE', '/admin/project/' + projectId + '/subsystem/' + urllib.parse.quote(name.encode('utf-8'))
            , '')

    # TODO this function is deprecated
    def createVersions(self, projectId, versions):
        """ Accepts result of getVersions()
        """

        for v in versions:
            self.createVersion(projectId, v)

    # TODO this function is deprecated
    def createVersion(self, projectId, v):
        return self.createVersionDetailed(projectId, v.name, v.isReleased, v.isArchived, releaseDate=v.releaseDate,
            description=v.description)

    # TODO this function is deprecated
    def createVersionDetailed(self, projectId, name, isReleased, isArchived, releaseDate=None, description=''):
        params = {'description': description,
                  'isReleased': str(isReleased),
                  'isArchived': str(isArchived)}
        if releaseDate is not None:
            params['releaseDate'] = str(releaseDate)
        return self._put(
            '/admin/project/' + urllib.parse.quote(projectId) + '/version/' + urllib.parse.quote(name.encode('utf-8')) + "?" +
            urllib.parse.urlencode(params))

    def getIssues(self, projectId, filter, after, max):
        #response, content = self._req('GET', '/project/issues/' + urllib.parse.quote(projectId) + "?" +
        path = '/issue'
        if projectId:
            path += '/byproject/' + urllib.parse.quote(projectId)
        url = path + "?" + urllib.parse.urlencode({'after': str(after),
                                                   'max': str(max),
                                                   'filter': filter})
        xml = self._getXml(url)
        return [youtrack.Issue(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getNumberOfIssues(self, filter = '', waitForServer=True):
        while True:
          urlFilterList = [('filter',filter)]
          finalUrl = '/issue/count?' + urllib.parse.urlencode(urlFilterList)
          response, content = self._req('GET', finalUrl, content_type="application/json")
          result = json.loads(content)
          numberOfIssues = result['value']
          if (not waitForServer):
            return numberOfIssues
          if (numberOfIssues!=-1):
            break

        time.sleep(5)
        return self.getNumberOfIssues(filter,False)


    def getAllSprints(self,agileID):
        xml = self._getXml('/agile/' + agileID + "/sprints?")
        return [(e.getAttribute('name'),e.getAttribute('start'),e.getAttribute('finish')) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def getAllIssues(self, filter = '', after = 0, max = 999999, withFields = ()):
        urlJobby = [('with',field) for field in withFields] + \
                    [('after',str(after)),
                    ('max',str(max)),
                    ('filter',filter)]
        xml = self._getXml('/issue' + "?" + urllib.parse.urlencode(urlJobby))
        return [youtrack.Issue(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def exportIssueLinks(self):
        xml = self._get('/export/links')
        return [youtrack.Link(e, self) for e in xml.documentElement.childNodes if e.nodeType == Node.ELEMENT_NODE]

    def executeCommand(self, issueId, command, comment=None, group=None, run_as=None, disable_notifications=False):
        if isinstance(command, str):
            command = command.encode('utf-8')
        params = {'command': command}

        if comment is not None:
            params['comment'] = comment

        if group is not None:
            params['group'] = group

        if run_as is not None:
            params['runAs'] = run_as

        if disable_notifications:
            params['disableNotifications'] = disable_notifications

        for p in params:
            if isinstance(params[p], str):
                params[p] = params[p].encode('utf-8')

        self._req('POST',
                  '/issue/' + issueId + "/execute",
                  body=urllib.parse.urlencode(params),
                  content_type='application/x-www-form-urlencoded')

        return "Command executed"

    def getCustomField(self, name):
        return youtrack.CustomField(self._get("/admin/customfield/field/" + urllib.parse.quote(name.encode('utf-8'))), self)

    def getCustomFields(self):
        xml = self._getXml('/admin/customfield/field')
        return [self.getCustomField(e.getAttribute('name')) for e in xml.documentElement.childNodes if
                e.nodeType == Node.ELEMENT_NODE]

    def createCustomField(self, cf):
        params = dict([])
        if hasattr(cf, "defaultBundle"):
            params["defaultBundle"] = cf.defaultBundle
        if hasattr(cf, "attachBundlePolicy"):
            params["attachBundlePolicy"] = cf.attachBundlePolicy
        auto_attached = False
        if hasattr(cf, "autoAttached"):
            auto_attached = cf.autoAttached
        return self.createCustomFieldDetailed(cf.name, cf.type, cf.isPrivate, cf.visibleByDefault, auto_attached,
            params)

    def createCustomFieldDetailed(self, customFieldName, typeName, isPrivate, defaultVisibility,
                                  auto_attached=False, additional_params=dict([])):
        params = {'type': typeName, 'isPrivate': str(isPrivate), 'defaultVisibility': str(defaultVisibility),
                  'autoAttached': str(auto_attached)}
        params.update(additional_params)
        for key in params:
            if isinstance(params[key], str):
                params[key] = params[key].encode('utf-8')

        self._put('/admin/customfield/field/' + urllib.parse.quote(customFieldName.encode('utf-8')) + '?' +
                  urllib.parse.urlencode(params), )

        return "Created"

    def createCustomFields(self, cfs):
        for cf in cfs:
            self.createCustomField(cf)

    def getProjectCustomField(self, projectId, name):
        if isinstance(name, str):
            name = name.encode('utf8')
        return youtrack.ProjectCustomField(
            self._get("/admin/project/" + urllib.parse.quote(projectId) + "/customfield/" + urllib.parse.quote(name))
            , self)

    def getProjectCustomFields(self, projectId):
        xml = self._getXml('/admin/project/' + urllib.parse.quote(projectId) + '/customfield')
        return [self.getProjectCustomField(projectId, e.getAttribute('name')) for e in
                xml.getElementsByTagName('projectCustomField')]

    def createProjectCustomField(self, projectId, pcf):
        return self.createProjectCustomFieldDetailed(projectId, pcf.name, pcf.emptyText, pcf.params)

    def createProjectCustomFieldDetailed(self, projectId, customFieldName, emptyFieldText, params=None):
        if not len(emptyFieldText.strip()):
            emptyFieldText = "No " + customFieldName
        if isinstance(customFieldName, str):
            customFieldName = customFieldName.encode('utf-8')
        _params = {'emptyFieldText': emptyFieldText}
        if params is not None:
            _params.update(params)
        for key in _params:
            if isinstance(_params[key], str):
                _params[key] = _params[key].encode('utf-8')
        return self._put(
            '/admin/project/' + projectId + '/customfield/' + urllib.parse.quote(customFieldName) + '?' +
            urllib.parse.urlencode(_params))

    def deleteProjectCustomField(self, project_id, pcf_name):
        self._req('DELETE', '/admin/project/' + urllib.parse.quote(project_id) + "/customfield/" + urllib.parse.quote(pcf_name))

    def getIssueLinkTypes(self):
        xml = self._getXml('/admin/issueLinkType')
        return [youtrack.IssueLinkType(e, self) for e in xml.getElementsByTagName('issueLinkType')]

    def createIssueLinkTypes(self, issueLinkTypes):
        for ilt in issueLinkTypes:
            return self.createIssueLinkType(ilt)

    def createIssueLinkType(self, ilt):
        return self.createIssueLinkTypeDetailed(ilt.name, ilt.outwardName, ilt.inwardName, ilt.directed)

    def createIssueLinkTypeDetailed(self, name, outwardName, inwardName, directed):
        if isinstance(name, str):
            name = name.encode('utf-8')
        if isinstance(outwardName, str):
            outwardName = outwardName.encode('utf-8')
        if isinstance(inwardName, str):
            inwardName = inwardName.encode('utf-8')
        return self._put('/admin/issueLinkType/' + urllib.parse.quote(name) + '?' +
                         urllib.parse.urlencode({'outwardName': outwardName,
                                           'inwardName': inwardName,
                                           'directed': directed}))

    def getEvents(self, issue_id):
        return self._get('/event/issueEvents/' + urllib.parse.quote(issue_id))

    def getWorkItems(self, issue_id):
        try:
            response, content = self._req('GET',
                '/issue/%s/timetracking/workitem' % urllib.parse.quote(issue_id), content_type="application/xml")
            xml = minidom.parseString(content)
            return [youtrack.WorkItem(e, self) for e in xml.documentElement.childNodes if
                    e.nodeType == Node.ELEMENT_NODE]
        except youtrack.YouTrackException as e:
            print("Can't get work items.", str(e))
            return []


    def createWorkItem(self, issue_id, work_item):
        xml =  '<workItem>'
        xml += '<date>%s</date>' % work_item.date
        xml += '<duration>%s</duration>' % work_item.duration
        if hasattr(work_item, 'description') and work_item.description is not None:
            xml += '<description>%s</description>' % escape(work_item.description)
        if hasattr(work_item, 'worktype') and work_item.worktype is not None:
            xml += '<worktype><name>%s</name></worktype>' % work_item.worktype
        xml += '</workItem>'
        if isinstance(xml, str):
            xml = xml.encode('utf-8')
        self._reqXml('POST',
            '/issue/%s/timetracking/workitem' % urllib.parse.quote(issue_id), xml)

    def importWorkItems(self, issue_id, work_items):
        xml = ''
        for work_item in work_items:
            xml +=  '<workItem>'
            xml += '<date>%s</date>' % work_item.date
            xml += '<duration>%s</duration>' % work_item.duration
            if hasattr(work_item, 'description') and work_item.description is not None:
                xml += '<description>%s</description>' % escape(work_item.description)
            if hasattr(work_item, 'worktype') and work_item.worktype is not None:
                xml += '<worktype><name>%s</name></worktype>' % work_item.worktype
            xml += '<author login=%s></author>' % quoteattr(work_item.authorLogin)
            xml += '</workItem>'
        if isinstance(xml, str):
            xml = xml.encode('utf-8')
        if xml:
            xml = '<workItems>' + xml + '</workItems>'
            try:
                self.headers['Accept'] = 'application/xml'
                self._reqXml(
                    'PUT',
                    '/import/issue/%s/workitems' % urllib.parse.quote(issue_id), xml)
            finally:
                del self.headers['Accept']

    def getSearchIntelliSense(self, query,
                              context=None, caret=None, options_limit=None):
        opts = {'filter': query}
        if context:
            opts['project'] = context
        if caret is not None:
            opts['caret'] = caret
        if options_limit is not None:
            opts['optionsLimit'] = options_limit
        return youtrack.IntelliSense(
            self._get('/issue/intellisense?' + urllib.parse.urlencode(opts)), self)

    def getCommandIntelliSense(self, issue_id, command,
                               run_as=None, caret=None, options_limit=None):
        opts = {'command': command}
        if run_as:
            opts['runAs'] = run_as
        if caret is not None:
            opts['caret'] = caret
        if options_limit is not None:
            opts['optionsLimit'] = options_limit
        return youtrack.IntelliSense(
            self._get('/issue/%s/execute/intellisense?%s'
                      % (issue_id, urllib.parse.urlencode(opts))), self)

    def getGlobalTimeTrackingSettings(self):
        try:
            cont = self._get('/admin/timetracking')
            return youtrack.GlobalTimeTrackingSettings(cont, self)
        except youtrack.YouTrackException as e:
            if e.response.status != 404:
                raise e

    def getProjectTimeTrackingSettings(self, projectId):
        try:
            cont = self._get('/admin/project/' + projectId + '/timetracking')
            return youtrack.ProjectTimeTrackingSettings(cont, self)
        except youtrack.YouTrackException as e:
            if e.response.status != 404:
                raise e

    def setGlobalTimeTrackingSettings(self, daysAWeek=None, hoursADay=None):
        xml = '<timesettings>'
        if daysAWeek is not None:
            xml += '<daysAWeek>%d</daysAWeek>' % daysAWeek
        if hoursADay is not None:
            xml += '<hoursADay>%d</hoursADay>' % hoursADay
        xml += '</timesettings>'
        return self._reqXml('PUT', '/admin/timetracking', xml)

    def setProjectTimeTrackingSettings(self,
        projectId, estimateField=None, timeSpentField=None, enabled=None):
        if enabled is not None:
            xml = '<settings enabled="%s">' % str(enabled == True).lower()
        else:
            xml = '<settings>'
        if estimateField is not None and estimateField != '':
            if isinstance(estimateField, str):
                estimateField = estimateField.encode('utf-8')
            xml += '<estimation name="%s"/>' % estimateField
        if timeSpentField is not None and timeSpentField != '':
            if isinstance(timeSpentField, str):
                timeSpentField = timeSpentField.encode('utf-8')
            xml += '<spentTime name="%s"/>' % timeSpentField
        xml += '</settings>'
        return self._reqXml(
            'PUT', '/admin/project/' + projectId + '/timetracking', xml)

    def get_work_types(self, project_id=None):
        if project_id:
            path = '/admin/project/%s/timetracking/worktype' % project_id
        else:
            path = '/admin/timetracking/worktype'
        try:
            xml = self._get(path)
            return [youtrack.WorkType(e, self)
                    for e in xml.documentElement.childNodes
                    if e.nodeType == Node.ELEMENT_NODE]
        except youtrack.YouTrackException as e:
            print(("Can't get work types", str(e)))
            return []

    def create_work_type(self, name=None, auto_attached=None, work_type=None):
        if work_type:
            wt = work_type
        else:
            if not name:
                raise ValueError("Work type name cannot be empty")
            wt = youtrack.WorkType()
            wt.name = name
            wt.autoAttached = auto_attached
        response, content = self._req(
            'POST', '/admin/timetracking/worktype', wt.toXml())
        return youtrack.WorkType(self._get(response['location']))

    def create_work_type_safe(self,
                              name=None, auto_attached=None, work_type=None):
        try:
            return self.create_work_type(name, auto_attached, work_type)
        except youtrack.YouTrackException as e:
            # Assume that this caused by not unique value and try to find
            # original work type
            if e.response.status not in (400, 409):
                raise e
            if work_type:
                name_lc = work_type.name.lower()
            else:
                name_lc = name.lower()
            for wt in self.get_work_types():
                if wt.name.lower() == name_lc:
                    return wt
            raise e

    def attach_work_type_to_project(self, project_id, work_type_id):
        self._req('PUT',
                  '/admin/project/%s/timetracking/worktype/%s' %
                  (project_id, work_type_id))

    def create_project_work_type(
            self, project_id, name=None, auto_attached=None, work_type=None):
        wt = self.create_work_type_safe(name, auto_attached, work_type)
        self.attach_work_type_to_project(project_id, wt.id)

    def getAllBundles(self, field_type):
        field_type = self.get_field_type(field_type)
        if field_type == "enum":
            tag_name = "enumFieldBundle"
        elif field_type == "user":
            tag_name = "userFieldBundle"
        else:
            tag_name = self.bundle_paths[field_type]
        names = [e.getAttribute("name") for e in self._get('/admin/customfield/' +
                                                           self.bundle_paths[field_type]).getElementsByTagName(
            tag_name)]
        return [self.getBundle(field_type, name) for name in names]


    def get_field_type(self, field_type):
        if "[" in field_type:
            field_type = field_type[0:-3]
        return field_type

    def getBundle(self, field_type, name):
        field_type = self.get_field_type(field_type)
        response = self._get('/admin/customfield/%s/%s' % (self.bundle_paths[field_type],
                                                           urllib.parse.quote(name.encode('utf-8'))))
        return self.bundle_types[field_type](response, self)

    def renameBundle(self, bundle, new_name):
        response, content = self._req("POST", "/admin/customfield/%s/%s?newName=%s" % (
            self.bundle_paths[bundle.get_field_type()], bundle.name, new_name), "", ignoreStatus=301)
        return response

    def createBundle(self, bundle):
        return self._reqXml('PUT', '/admin/customfield/' + self.bundle_paths[bundle.get_field_type()],
            body=bundle.toXml(), ignoreStatus=400)

    def deleteBundle(self, bundle):
        response, content = self._req("DELETE", "/admin/customfield/%s/%s" % (
            self.bundle_paths[bundle.get_field_type()], bundle.name), "")
        return response

    def addValueToBundle(self, bundle, value):
        request = ""
        if bundle.get_field_type() != "user":
            request = "/admin/customfield/%s/%s/" % (
                self.bundle_paths[bundle.get_field_type()], urllib.parse.quote(bundle.name.encode('utf-8')))
            if isinstance(value, str):
                request += urllib.parse.quote(value)
            elif isinstance(value, str):
                request += urllib.parse.quote(value.encode('utf-8'))
            else:
                request += urllib.parse.quote(value.name.encode('utf-8')) + "?"
                params = dict()
                for e in value:
                    if (e != "name") and (e != "element_name") and len(value[e]):
                        if isinstance(value[e], str):
                            params[e] = value[e].encode('utf-8')
                        else:
                            params[e] = value[e]
                if len(params):
                    request += urllib.parse.urlencode(params)
        else:
            request = "/admin/customfield/userBundle/%s/" % urllib.parse.quote(bundle.name.encode('utf-8'))
            if isinstance(value, youtrack.User):
                request += "individual/%s/" % value.login
            elif isinstance(value, youtrack.Group):
                request += "group/%s/" % urllib.parse.quote(value.name.encode('utf-8'))
            else:
                request += "individual/%s/" % urllib.parse.quote(value)
        return self._put(request)

    def removeValueFromBundle(self, bundle, value):
        field_type = bundle.get_field_type()
        request = "/admin/customfield/%s/%s/" % (self.bundle_paths[field_type], bundle.name)
        if field_type != "user":
            request += urllib.parse.quote(value.name)
        elif isinstance(value, youtrack.User):
            request += "individual/" + urllib.parse.quote(value.login)
        else:
            request += "group/" + value.name
        response, content = self._req("DELETE", request, "", ignoreStatus=204)
        return response


    def getEnumBundle(self, name):
        return youtrack.EnumBundle(self._get("/admin/customfield/bundle/" + urllib.parse.quote(name)), self)


    def createEnumBundle(self, eb):
        return self.createBundle(eb)

    def deleteEnumBundle(self, name):
        return self.deleteBundle(self.getEnumBundle(name))

    def createEnumBundleDetailed(self, name, values):
        xml = '<enumeration name=\"' + name.encode('utf-8') + '\">'
        xml += ' '.join('<value>' + v + '</value>' for v in values)
        xml += '</enumeration>'
        return self._reqXml('PUT', '/admin/customfield/bundle', body=xml.encode('utf8'), ignoreStatus=400)

    def addValueToEnumBundle(self, name, value):
        return self.addValueToBundle(self.getEnumBundle(name), value)

    def addValuesToEnumBundle(self, name, values):
        return ", ".join(self.addValueToEnumBundle(name, value) for value in values)

    def getYouTrackBuildNumber(self):
        response, content = self._req('GET',
                                      self.url + '/api/config?fields=build',
                                      ignoreStatus=404,
                                      content_type='application/json')
        if response.status != 200 or not content:
            return 0
        try:
            return int(json.loads(content).get('build', 0))
        except ValueError:
            return 0

    def isMarkdownSupported(self):
        return self.getYouTrackBuildNumber() > 39406

    bundle_paths = {
        "enum": "bundle",
        "build": "buildBundle",
        "ownedField": "ownedFieldBundle",
        "state": "stateBundle",
        "version": "versionBundle",
        "user": "userBundle"
    }

    bundle_types = {
        "enum": lambda xml, yt: youtrack.EnumBundle(xml, yt),
        "build": lambda xml, yt: youtrack.BuildBundle(xml, yt),
        "ownedField": lambda xml, yt: youtrack.OwnedFieldBundle(xml, yt),
        "state": lambda xml, yt: youtrack.StateBundle(xml, yt),
        "version": lambda xml, yt: youtrack.VersionBundle(xml, yt),
        "user": lambda xml, yt: youtrack.UserBundle(xml, yt)
    }

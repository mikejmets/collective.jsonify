from wrapper import Wrapper
try:
    import binascii
    def _base64decode(s):
        return binascii.a2b_base64(s)
except:
    import base64
    def _base64decode(s):
        return base64.b64decode(s)
from plone import api
import pprint
import sys
import os
import traceback
from urllib2 import urlopen

try:
    import simplejson as json
except:
    import json


def _clean_dict(dct, error):
    """Remove dictionary items, which threw an error.
    """
    new_dict = dct.copy()
    message = str(error)
    for key, value in dct.items():
        if message.startswith(repr(value)):
            del new_dict[key]
            return key, new_dict
    raise ValueError("Could not clean up object %s" % dct['_id'])


def get_item(self):
    """
    """

    try:
        context_dict = Wrapper(self)
    except Exception, e:
        cwd = os.getcwd()
        etype = sys.exc_info()[0]
        tb = pprint.pformat(traceback.format_tb(sys.exc_info()[2]))
        return 'ERROR: %s exception wrapping object: %s: %s\n%s' % (
            cwd, etype, str(e), tb
        )

    passed = False
    while not passed:
        try:
            JSON = json.dumps(context_dict)
            passed = True
        except Exception, error:
            if "serializable" in str(error):
                key, context_dict = _clean_dict(context_dict, error)
                pprint.pprint(
                    'Not serializable member %s of %s ignored' % (
                        key, repr(self)
                    )
                )
                passed = False
            else:
                return ('ERROR: Unknown error serializing object: %s' % error)
    self.REQUEST.response.setHeader("Content-type", "application/json")
    return JSON


def get_children(self):
    """
    """
    from Acquisition import aq_base

    portal_type = self.REQUEST.form.get('portal_type', None)
    children = []
    if portal_type == 'Member':
        users  = api.user.get_users()
        # all_groups = api.group.get_groups()
        for user in users:
            group_ids = ""
            groups = []  # api.group.get_groups(user=user)
            if groups:
                group_ids = [g.id for g in groups]
                group_ids = ', '.join(group_ids)
            children.append({
                'id': user.id,
                'email': user.getProperty('email', '').decode('utf-8'),
                'fullname': user.getProperty('fullname', ''),
                'groups': group_ids,
            })

    broken = []
    if getattr(aq_base(self), 'objectIds', False):
        values = self.values()
        # Btree based folders return an OOBTreeItems
        # object which is not serializable
        # Thus we need to convert it to a list
        for child in values:
            if portal_type is None or (hasattr(child, 'portal_type') and child.portal_type == portal_type):
                group_id = ""
                local_roles = child.get_local_roles()
                for role in local_roles:
                    if role[0].startswith('M_') and 'Owner' in role[1]:
                        group_id = role[0]
                        break

                owners = []
                if group_id:
                    users = api.user.get_users(groupname=group_id) 
                    if users:
                        for user in users:
                            owners.append({
                                'id': user.id,
                                'email': user.getProperty('email', '').decode('utf-8'),
                                'fullname': user.getProperty('fullname', ''),
                            })

                adict = {
                    'id': child.id,
                    'title': child.title,
                    'children_url': '{}/get_children'.format(child.absolute_url()),
                    'item_url': '{}/get_item'.format(child.absolute_url()),
                    'portal_type': child.portal_type,
                    'group_id': group_id,
                    'owners': owners,
                }
                if False and portal_type == 'MemberContainer':
                    url = adict['item_url']
                    try:
                        response = urlopen(url)
                        values = response.read()
                        context_dict = json.loads(values)
                        adict['reviews'] = context_dict['reviews']
                    except Exception as e:
                        # raise RuntimeError('Error acceessing id {} url {}: {}'.format(child.id, url, e))
                        print('Error acceessing id {} url {}: {}'.format(child.id, url, e))
                        # broken.append({'id': child.id, 'url': url, 'error': e})
                        # broken.append({'id': child.id, 'url': url})
                        broken.append({'id': child.id})
                children.append(adict)
            
    if len(broken):
        children.append({'broken': broken})
    self.REQUEST.response.setHeader("Content-type", "application/json")
    return json.dumps(children)


def get_catalog_results(self):
    """Returns a list of paths of all items found by the catalog.
       Query parameters can be passed in the request.
    """
    print('get_catalog_results')
    if not hasattr(self.aq_base, 'unrestrictedSearchResults'):
        return
    query = self.REQUEST.form.get('catalog_query', None)
    if query:
        query = eval(_base64decode(query),
                     {"__builtins__": None}, {})
    item_paths = [item.getPath() for item
                  in self.unrestrictedSearchResults(**query)]
    self.REQUEST.response.setHeader("Content-type", "application/json")
    return json.dumps(item_paths)

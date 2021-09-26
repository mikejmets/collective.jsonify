from Acquisition import aq_base
from DateTime import DateTime
import json
from Products.CMFCore.utils import getToolByName
import datetime
import os
from plone import api
try:
    from plone.uuid.interfaces import IUUID
    HASPLONEUUID = True
except ImportError:
    HASPLONEUUID = False

try:
    try:    # This version doesn't consume as much memory
        from binascii import b2a_base64
        def _base64encode(data):
            return b2a_base64(data)
    except ImportError:
        from base64 import b64encode
        def _base64encode(data):
            return b64encode(data)
except ImportError:
    # Legacy version of base64 (eg on Python 2.2)
    from base64 import encodestring as b64encode
    def _base64encode(data):
        return b64encode(data)

def _get_brains(context, portal_type, review_states):
    catalog = api.portal.get_tool("portal_catalog")
    path = '/'.join(context.getPhysicalPath())
    brains = catalog( portal_type=portal_type, path=path) 
    # review_state=review_states
    print(path)
    print(len(brains))
    return brains


class Wrapper(dict):
    """Gets the data in a format that can be used by the transmogrifier
    blueprints in collective.jsonmigrator.
    """

    def __init__(self, context):
        self.context = context
        self._context = aq_base(context)
        self.charset = None
        try:
            from Products.CMFCore.utils import getToolByName
            self.portal = getToolByName(
                self.context, 'portal_url').getPortalObject()
            self.portal_path = '/'.join(self.portal.getPhysicalPath())
            self.portal_utils = getToolByName(
                self.context, 'plone_utils', None)
            try:
                self.charset = self.portal.portal_properties.site_properties.default_charset  # noqa
            except AttributeError:
                pass
        except ImportError:
            pass

        # never seen it missing ... but users can change it
        if not self.charset:
            self.charset = 'utf-8'

        for method in dir(self):
            if method.startswith('get_'):
                getattr(self, method)()

        if self.context.portal_type == 'MemberContiner':
            self.get_member_container_review()

    def providedBy(self, iface, ctx):
        # Handle zope.interface and Interface interfaces.
        if getattr(iface, 'providedBy', False):
            ret = iface.providedBy(ctx)
        elif getattr(iface, 'isImplementedBy', False):
            ret = iface.isImplementedBy(ctx)
        return bool(ret)

    def decode(self, s, encodings=('utf8', 'latin1', 'ascii')):
        """Sometimes we have to guess charset
        """
        if callable(s):
            s = s()
        if isinstance(s, unicode):
            return s
        test_encodings = encodings
        if self.charset:
            test_encodings = (self.charset, ) + test_encodings
        for encoding in test_encodings:
            try:
                return s.decode(encoding)
            except:
                pass
        return s.decode(test_encodings[0], 'ignore')

    def _serialize_file(self, value):
        if hasattr(value, 'open'):
            data = value.open().read()
        else:
            data = value.data

        try:
            max_filesize = int(
                os.environ.get('JSONIFY_MAX_FILESIZE', 20000000))
        except ValueError:
            max_filesize = 20000000

        if data and len(data) > max_filesize:
            raise ValueError

        ctype = value.contentType
        size = value.getSize()
        dvalue = {
            'data': _base64encode(data),
            'size': size,
            'filename': value.filename or '',
            'content_type': ctype,
            'encoding': 'base64'
        }
        return dvalue

    def get_dexterity_fields(self):
        """If dexterity is used then extract fields.
        """
        try:
            from plone.dexterity.interfaces import IDexterityContent
            if not self.providedBy(IDexterityContent, self.context):
                return
            from plone.dexterity.utils import iterSchemata
            # from plone.uuid.interfaces import IUUID
            from zope.schema import getFieldsInOrder
            from datetime import date
        except:
            return

        # get all fields for this obj
        for schemata in iterSchemata(self.context):
            for fieldname, field in getFieldsInOrder(schemata):
                try:
                    value = field.get(schemata(self.context))
                    # value = getattr(context, name).__class__.__name__
                except AttributeError:
                    continue
                if value is field.missing_value:
                    continue

                field_type = field.__class__.__name__
                try:
                    field_value_type = field.value_type.__class__.__name__
                except AttributeError:
                    field_value_type = None

                if field_type in ('RichText',):
                    # TODO: content_type missing
                    value = unicode(value.raw)

                elif field_type in (
                    'List',
                    'Tuple',
                ) and field_value_type in (
                    'NamedImage',
                    'NamedBlobImage',
                    'NamedFile',
                    'NamedBlobFile'
                ):
                    fieldname = unicode('_datafield_' + fieldname)
                    _value = []
                    for item in value:
                        try:
                            _value.append(self._serialize_file(item))
                        except ValueError:
                            continue
                    value = _value

                elif field_type in (
                    'NamedImage',
                    'NamedBlobImage',
                    'NamedFile',
                    'NamedBlobFile'
                ):
                    # still to test above with NamedFile & NamedBlobFile
                    fieldname = unicode('_datafield_' + fieldname)
                    try:
                        value = self._serialize_file(value)
                    except ValueError:
                        continue

                elif field_type in (
                    'RelationList',
                ) and field_value_type in (
                    'RelationChoice',
                ):
                    _value = []
                    for item in value:
                        try:
                            # Simply export the path to the relation. Postprocessing when importing is needed.
                            _value.append(item.to_path)
                        except ValueError:
                            continue
                    value = _value

                elif field_type == 'GeolocationField':
                    # super special plone.formwidget.geolocation case
                    self['latitude'] = getattr(value, 'latitude', 0)
                    self['longitude'] = getattr(value, 'longitude', 0)
                    continue

                elif isinstance(value, date):
                    value = value.isoformat()

                # elif field_type in ('TextLine',):
                else:
                    BASIC_TYPES = (
                        unicode, int, long, float, bool, type(None),
                        list, tuple, dict
                    )
                    if type(value) in BASIC_TYPES:
                        pass
                    else:
                        # E.g. DateTime or datetime are nicely representated
                        value = unicode(value)

                self[unicode(fieldname)] = value

    def _get_at_field_value(self, field):
        if field.accessor is not None:
            return getattr(self.context, field.accessor)()
        return field.get(self.context)

    def get_archetypes_fields(self):
        """If Archetypes is used then dump schema.
        """
        try:
            from Products.Archetypes.interfaces import IBaseObject
            if not self.providedBy(IBaseObject, self.context):
                return
        except:
            return

        try:
            from archetypes.schemaextender.interfaces import IExtensionField
        except:
            IExtensionField = None

        fields = []
        for schemata in self.context.Schemata().values():
            fields.extend(schemata.fields())

        for field in fields:
            fieldname = unicode(field.__name__)
            type_ = field.__class__.__name__

            try:
                if self.providedBy(IExtensionField, field):
                    # archetypes.schemaextender case:
                    # Try to get the base class of the schemaexter-field, which
                    # is not an extension field.
                    type_ = [
                        it.__name__ for it in field.__class__.__bases__
                        if not IExtensionField.implementedBy(it)
                    ][0]
            except:
                pass

            fieldnames = [
                'BooleanField',
                'ComputedField',
                'DataGridField',
                'EmailField',
                'FixedPointField',
                'FloatField',
                'IntegerField',
                'LinesField',
                'SimpleDataGridField',
                'StringField',
                'TALESLines',
                'TALESString',
                'TextField',
                'ZPTField',
            ]

            if type_ in fieldnames:
                try:
                    value = field.getRaw(self.context)
                except AttributeError:
                    try:
                        value = self._get_at_field_value(field)
                    except TypeError:
                        value = ''

                if callable(value):
                    value = value()

                if value and type_ in ['ComputedField']:
                    if isinstance(value, str):
                        value = self.decode(value)

                if value and type_ in ['StringField', 'TextField']:
                    try:
                        value = self.decode(value)
                    except AttributeError:
                        # maybe an int?
                        value = unicode(value)
                    except Exception, e:
                        raise Exception('problems with %s: %s' % (
                            self.context.absolute_url(), str(e))
                        )
                elif value and type_ == 'DataGridField':
                    for i, row in enumerate(value):
                        for col_key in row.keys():
                            col_value = row[col_key]
                            if type(col_value) in (unicode, str):
                                value[i][col_key] = self.decode(col_value)

                self[unicode(fieldname)] = value

                if value and type_ in ['StringField', 'TextField']:
                    try:
                        ct = field.getContentType(self.context)
                        self[unicode('_content_type_') + fieldname] = ct
                    except AttributeError:
                        pass

            elif type_ in ['DateTimeField', ]:
                value = str(self._get_at_field_value(field))
                if value:
                    self[unicode(fieldname)] = value

            elif type_ in [
                'ImageField',
                'FileField',
                'BlobField',
                'AttachmentField',
                'ExtensionBlobField',
            ]:
                fieldname = unicode('_datafield_' + fieldname)
                value = self._get_at_field_value(field)
                value2 = value

                if value and not isinstance(value, str):
                    if isinstance(getattr(value, 'data', None), str):
                        value = _base64encode(value.data)
                    else:
                        data = value.data
                        value = ''
                        while data is not None:
                            value += data.data
                            data = data.next
                        value = _base64encode(value)

                try:
                    max_filesize = int(
                        os.environ.get('JSONIFY_MAX_FILESIZE', 20000000)
                    )
                except ValueError:
                    max_filesize = 20000000

                if value and len(value) < max_filesize:
                    size = value2.getSize()
                    try:
                        fname = field.getFilename(self.context)
                    except AttributeError:
                        fname = value2.getFilename()

                    try:
                        fname = self.decode(fname)
                    except AttributeError:
                        # maybe an int?
                        fname = unicode(fname)
                    except Exception, e:
                        raise Exception(
                            'problems with %s: %s' % (
                                self.context.absolute_url(), str(e)
                            )
                        )

                    try:
                        ctype = field.getContentType(self.context)
                    except AttributeError:
                        ctype = value2.getContentType()

                    self[fieldname] = {
                        'data': value,
                        'size': size,
                        'filename': fname or '',
                        'content_type': ctype,
                        'encoding': 'base64'
                    }

            elif type_ in [
                'ReferenceField',
            ]:
                # If there are references, add the UIDs to the referenced
                # contents
                value = field.getRaw(self.context)
                if value:
                    self[fieldname] = value

            elif type_ in ['QueryField']:
                value = field.getRaw(self.context)
                self[fieldname] = [dict(q) for q in value]

            elif type_ in [
                'RecordsField',  # from Products.ATExtensions
                'RecordField',
                'FormattableNamesField',
                'FormattableNameField'
            ]:
                # ATExtensions fields
                # convert items to real dicts
                # value = [dict(it) for it in field.get(self.context)]

                def _enc(val):
                    if type(val) in (unicode, str):
                        val = self.decode(val)
                    return val

                value = []
                for it in field.get(self.context):
                    it = dict(it)
                    val_ = {}
                    for k_, v_ in it.items():
                        val_[_enc(k_)] = _enc(v_)
                    value.append(val_)

                self[unicode(fieldname)] = value

            else:
                # Just try to stringify value
                try:
                    value = field.getRaw(self.context)
                except AttributeError:
                    value = self._get_at_field_value(field)
                self[unicode(fieldname)] = self.decode(str(value))

    def get_references(self):
        """AT references.
        """
        try:
            from Products.Archetypes.interfaces import IReferenceable
            if not self.providedBy(IReferenceable, self.context):
                return
        except:
            return

        self['_atrefs'] = {}
        self['_atbrefs'] = {}
        relationships = self.context.getRelationships()
        for rel in relationships:
            self['_atrefs'][rel] = []
            refs = self.context.getRefs(relationship=rel)
            for ref in refs:
                if ref is not None:
                    self['_atrefs'][rel].append(
                        '/'.join(ref.getPhysicalPath()))
        brelationships = self.context.getBRelationships()
        for brel in brelationships:
            self['_atbrefs'][brel] = []
            brefs = self.context.getBRefs(relationship=brel)
            for bref in brefs:
                if bref is not None:
                    self['_atbrefs'][brel].append(
                        '/'.join(bref.getPhysicalPath()))

    def get_uid(self):
        """Unique ID of object
        Example::
            {'_uid': '12jk3h1kj23h123jkh13kj1k23jh1'}
        """
        if hasattr(self._context, 'UID'):
            self['_uid'] = self.context.UID()
        elif HASPLONEUUID:
            self['_uid'] = IUUID(self.context.aq_base, None)

    def get_id(self):
        """Object id
        :keys: _id
        """
        self['_id'] = self.context.getId()

    def get_path(self):
        """Path of object
        Example::
            {'_path': '/Plone/first-page'}
        """
        self['_path'] = '/'.join(self.context.getPhysicalPath())

    def get_type(self):
        """Portal type of object
        Example::
            {'_type': 'Document'}
        """
        try:
            self['_type'] = self.context.portal_type
        except AttributeError:
            pass

    def get_classname(self):
        """Classname of object.
        Sometimes in old Plone sites we dont know exactly which type we are
        using.
        Example::
           {'_classname': 'ATDocument'}
        """
        self['_classname'] = self.context.__class__.__name__

    def get_properties(self):
        """Object properties
        :keys: _properties
        """
        self['_properties'] = []
        if getattr(self.context, 'propertyIds', False):
            for pid in self.context.propertyIds():
                val = self.context.getProperty(pid)
                typ = self.context.getPropertyType(pid)
                if typ == 'string' and isinstance(val, str):
                    val = self.decode(val)
                if isinstance(val, DateTime)\
                        or isinstance(val, datetime.time)\
                        or isinstance(val, datetime.datetime)\
                        or isinstance(val, datetime.date):
                    val = unicode(val)
                self['_properties'].append(
                    (pid, val, self.context.getPropertyType(pid))
                )

    def get_directly_provided_interfaces(self):
        try:
            from zope.interface import directlyProvidedBy
        except:
            return
        self['_directly_provided'] = [
            it.__identifier__ for it in directlyProvidedBy(self.context)
        ]

    def get_defaultview(self):
        """Default view of object
        :keys: _layout, _defaultpage
        """
        try:
            # When migrating Zope folders to Plone folders
            # set defaultpage to "index_html"
            from Products.CMFCore.PortalFolder import PortalFolder
            if isinstance(self.context, PortalFolder):
                self['_defaultpage'] = 'index_html'
                return
        except:
            pass

        _default = ''
        try:
            _default = '/'.join(
                self.portal_utils.browserDefault(self.context)[1])
        except AttributeError:
            pass

        _layout = ''
        try:
            _layout = self.context.getLayout()
        except:
            pass

        if _default and _layout and _default == _layout:
            # browserDefault always returns the layout, but we only want to set
            # the defaultpage, if it's different from the layout
            _default = ''

        self['_defaultpage'] = _default
        self['_layout'] = _layout

    def get_format(self):
        """Format of object
        :keys: _format
        """
        try:
            self['_content_type'] = self.context.Format()
        except:
            pass

    def get_local_roles(self):
        """Local roles of object
        :keys: _ac_local_roles
        """
        self['_ac_local_roles'] = {}
        if getattr(self.context, '__ac_local_roles__', False):
            for key, val in self.context.__ac_local_roles__.items():
                if key is not None:
                    self['_ac_local_roles'][key] = val

    def get_userdefined_roles(self):
        """User defined roles for object (via sharing UI)
        :keys: _userdefined_roles
        """
        self['_userdefined_roles'] = ()
        if getattr(self.context, 'userdefined_roles', False):
            self['_userdefined_roles'] = self.context.userdefined_roles()

    def get_permissions(self):
        """Permission of object (Security tab in ZMI)
        :keys: _permissions
        """
        self['_permissions'] = {}
        if getattr(self.context, 'permission_settings', False):
            roles = self.context.validRoles()
            ps = self.context.permission_settings()
            for perm in ps:
                unchecked = 0
                if not perm['acquire']:
                    unchecked = 1
                new_roles = []
                for role in perm['roles']:
                    if role['checked']:
                        role_idx = role['name'].index('r') + 1
                        role_name = roles[int(role['name'][role_idx:])]
                        new_roles.append(role_name)
                if unchecked or new_roles:
                    self['_permissions'][perm['name']] = {
                        'acquire': not unchecked,
                        'roles': new_roles
                    }

    def get_owner(self):
        """Object owner
        :keys: _owner
        """
        try:
            try:
                try:
                    self['_owner'] = self.context.getWrappedOwner().getId()
                except:
                    self['_owner'] = self.context.getOwner(info=1).getId()
            except:
                self['_owner'] = self.context.getOwner(info=1)[1]
        except:
            pass

    def get_workflowhistory(self):
        """Workflow history
        :keys: _workflow_history
        Example:::
            lalala
        """
        self['_workflow_history'] = {}
        if getattr(self.context, 'workflow_history', False):
            workflow_history = self.context.workflow_history.data
            for w in workflow_history:
                for i, w2 in enumerate(workflow_history[w]):
                    if 'time' in workflow_history[w][i].keys():
                        workflow_history[w][i]['time'] = str(
                            workflow_history[w][i]['time'])
                    if 'comments' in workflow_history[w][i].keys():
                        workflow_history[w][i]['comments'] =\
                            self.decode(workflow_history[w][i]['comments'])
                    if 'review_history' in workflow_history[w][i].keys():
                        workflow_history[w][i]['review_history'] = []
                        # This causes indefinite loop for some objects
                        # for j, w3 in enumerate(workflow_history[w][i]['review_history']):
                        #     if 'time' in workflow_history[w][i]['review_history'][j].keys():
                        #         workflow_history[w][i]['review_history'][j]['time'] = str(
                        #             workflow_history[w][i]['review_history'][j]['time'])
            self['_workflow_history'] = workflow_history

    def get_position_in_parent(self):
        """Get position in parent
        :keys: _gopip
        """
        try:
            from Products.CMFPlone.CatalogTool import getObjPositionInParent
        except ImportError:
            return

        pos = getObjPositionInParent(self.context)

        # After plone 3.3 the above method returns a 'DelegatingIndexer' rather
        # than an int
        try:
            from plone.indexer.interfaces import IIndexer
            if self.providedBy(IIndexer, pos):
                self['_gopip'] = pos()
                return
        except ImportError:
            pass

        self['_gopip'] = pos

    def get_translation(self):
        """ Get LinguaPlone translation linking information.
        """
        if not hasattr(self._context, 'getCanonical'):
            return

        translations = self.context.getTranslations()
        self['_translations'] = {}

        for lang in translations:
            trans_obj = '/'.join(translations[lang][0].getPhysicalPath())[len(self.portal_path):]
            self['_translations'][lang] = trans_obj

        self['_translationOf'] = '/'.join(self.context.getCanonical(
                                 ).getPhysicalPath())[len(self.portal_path):]
        self['_canonicalTranslation'] = self.context.isCanonical()

    def _is_cmf_only_obj(self):
        """Test, if a content item is a CMF only object.
        """
        context = self.context
        try:
            from Products.ATContentTypes.interface.interfaces import IATContentType  # noqa
            if self.providedBy(IATContentType, context):
                return False
        except:
            pass
        try:
            from Products.ATContentTypes.interfaces import IATContentType
            if self.providedBy(IATContentType, context):
                return False
        except:
            pass
        try:
            from plone.dexterity.interfaces import IDexterityContent
            if self.providedBy(IDexterityContent, context):
                return False
        except:
            pass
        try:
            from Products.CMFCore.DynamicType import DynamicType
            # restrict this to non archetypes/dexterity
            if isinstance(context, DynamicType):
                return True
        except:
            pass
        return False

    def get_zope_dublin_core(self):
        """If CMFCore is used in an old Zope site, then dump the
        Dublin Core fields
        """
        if not self._is_cmf_only_obj():
            return

        # strings
        for field in ('title', 'description', 'rights', 'language'):
            val = getattr(self.context, field, False)
            if val:
                self[field] = self.decode(val)
            else:
                self[field] = ''
        # tuples
        for field in ('subject', 'contributors'):
            self[field] = []
            val_tuple = getattr(self.context, field, False)
            if not val_tuple:
                # At least on Plone 2.5 we need Subject and Contributors
                # with a first capital letter.
                val_tuple = getattr(self.context, field.title(), False)
                if callable(val_tuple):
                    val_tuple = val_tuple()
            if val_tuple:
                for val in val_tuple:
                    self[field].append(self.decode(val))
                self[field] = tuple(self[field])
            else:
                self[field] = ()
        # datetime fields
        for field in ['creation_date', 'expiration_date',
                      'effective_date', 'expirationDate', 'effectiveDate']:
            val = getattr(self.context, field, False)
            if val:
                self[field] = str(val)
            else:
                self[field] = ''
        # modification_date:
        # bobobase_modification_time seems to have better data than
        # modification_date in Zope 2.6.4 - 2.9.7
        val = self.context.bobobase_modification_time()
        if val:
            self['modification_date'] = str(val)
        else:
            self['modification_date'] = ''

    def get_basic_dates(self):
        """ Dump creation and modification dates for items
        that are not "cmf-only". For dexterity for instance, these
        are not included in behaviors and so are not included in the
        iteration over schematas and fields in get_dexterity_fields().
        """
        if self._is_cmf_only_obj():
            # then the dates are handled by get_zope_dublin_core,
            # so we do nothing.
            return
        # datetime fields
        for field in ['creation_date', 'modification_date']:
            val = getattr(self.context.aq_base, field, False)
            if val:
                self[field] = str(val)
            else:
                self[field] = ''

    def get_zope_cmfcore_fields(self):
        """If CMFCore is used in an old Zope site, then dump the fields we know
        about.
        """
        if not self._is_cmf_only_obj():
            return

        self['_cmfcore_marker'] = 'yes'

        # For Link & Favourite types - field name has changed in Archetypes &
        # Dexterity
        if hasattr(self.context, 'remote_url'):
            self['remoteUrl'] = self.decode(
                getattr(
                    self.context,
                    'remote_url'))

        # For Document & News items
        if hasattr(self.context, 'text'):
            self['text'] = self.decode(getattr(self.context, 'text'))
        if hasattr(self.context, 'text_format'):
            self['text_format'] = self.decode(
                getattr(
                    self.context,
                    'text_format'))

        # Found in Document & News items, but not sure if this is necessary
        if hasattr(self.context, 'safety_belt'):
            self['safety_belt'] = self.decode(
                getattr(
                    self.context,
                    'safety_belt'))

        # Found in File & Image types, but not sure if this is necessary
        if hasattr(self.context, 'precondition'):
            self['precondition'] = self.decode(
                getattr(
                    self.context,
                    'precondition'))

        data_type = self.context.portal_type

        if data_type in ['File', 'Image']:
            fieldname = unicode('_datafield_%s' % data_type.lower())
            value = self.context
            orig_value = value

            if not isinstance(value, str):

                if isinstance(value.data, str):
                    value = _base64encode(value.data)
                else:
                    data = value.data
                    value = ''
                    while data is not None:
                        value += data.data
                        data = data.next
                    value = _base64encode(value)

            try:
                max_filesize = int(
                    os.environ.get(
                        'JSONIFY_MAX_FILESIZE',
                        20000000))
            except ValueError:
                max_filesize = 20000000

            if value and len(value) < max_filesize:
                size = orig_value.getSize()
                fname = orig_value.getId()
                try:
                    fname = self.decode(fname)
                except AttributeError:
                    # maybe an int?
                    fname = unicode(fname)
                except Exception, e:
                    raise Exception('problems with %s: %s' %
                                    (self.context.absolute_url(), str(e)))

                ctype = orig_value.getContentType()
                self[fieldname] = {
                    'data': value,
                    'size': size,
                    'filename': fname or '',
                    'content_type': ctype,
                    'encoding': 'base64'
                }

    def get_zopeobject_document_src(self):
        if not self._is_cmf_only_obj():
            return
        document_src = getattr(self.context, 'document_src', None)
        if document_src:
            self['document_src'] = self.decode(document_src())
        else:
            self['_zopeobject_document_src'] = ''


    def get_history(self):
        """ Export the history - metadata
        """
        try:
            repo_tool = getToolByName(self.context, "portal_repository")
            history_metadata = repo_tool.getHistoryMetadata(self.context)
            if not(hasattr(history_metadata,'getLength')):
                # No history metadata
                return

            history_list = []
            # Count backwards from most recent to least recent
            for i in xrange(history_metadata.getLength(countPurged=False)-1, -1, -1):
                data = history_metadata.retrieve(i, countPurged=False)
                meta = data["metadata"]["sys_metadata"].copy()
                version_id = history_metadata.getVersionId(i, countPurged=False)
                try:
                    dateaux = datetime.datetime.fromtimestamp(meta.get('timestamp',0))
                    meta['timestamp'] = dateaux.strftime("%Y/%m/%d %H:%M:%S GMT")
                except Exception, ex:
                    meta['timestamp']=''
                history_list.append(meta)
            self['_history'] = history_list

        except:
            pass

    def get_redirects(self):
        """Export plone.app.redirector redirects, if available.
        Comply with default expectations of redirector section in
        plone.app.transmogrifier: use the same key name "_old_paths"
        and don't include the site name on the path.
        """
        try:
            from zope.component import getUtility
            from plone.app.redirector.interfaces import IRedirectionStorage
            storage = getUtility(IRedirectionStorage)
            redirects = storage.redirects('/'.join(self.context.getPhysicalPath()))
            if redirects:
                # remove site name (e.g. "/Plone") from redirect paths
                self['_old_paths'] = [r[len(self.portal_path):] for r in redirects]
        except:  # noqa: E722
            pass

    def _load_registry_app(self, filename):
        try:
            f = open(filename)
            txt = f.read()
            f.close()
        except Exception as e:
            print('_load_registry_app failed on {}: {}'.format(filename, e))
            raise
            # return ""
        txt = txt.replace("\'s", ' s')
        txt = txt.replace("\'", '"')
        txt = txt.replace('\n', '')
        txt = txt.replace('\\u2013', '-')
        txt = txt.replace('\\u2018', '-')
        txt = txt.replace('\\u2019', '-')
        txt = txt.replace('None', 'null')
        txt = txt.replace('True', 'true')
        txt = txt.replace('False', 'false')
        txt = txt.replace(' u"', ' "')
        txt = txt.decode('utf-8-sig', errors='ignore')
        txt = self.decode(txt)
        lst = [i for i in txt.split(' ') if i.startswith('\\u')]
        if len(lst) > 0:
            import pdb; pdb.set_trace()
        try:
            txt = json.loads(txt)
        except Exception as e:
            import pdb; pdb.set_trace()
        return txt

    def _process_form_values(self, form_values):
        result = {}
        if form_values is None:
            return result

        for form_value in form_values:
            # print('get_member_container_review: form_value: {}'.format(form_value))
            fid = form_value['fid']
            fid_items = fid.split('_')
            if len(fid_items[0]) == 32:
                fid = '_'.join(fid_items[1:])
            if form_value.get('form'):
                if len(form_value.get('form', [])) == 1:
                    result[fid] = form_value['form'][0]
                elif len(form_value.get('form', [])) > 1:
                    subforms = []
                    for item in form_value.get('form', []):
                        # if item.get('vocabulary_words', None) is None and item.get('data', None) is None and len(item.get('ftitle', '')) == 0:
                        if item.get('data', None) is None:
                            # Empty record
                            continue
                        subforms.append(item)
                    if len(subforms) == 0:
                        result[fid] = form_value['form'][0]
                    elif len(subforms) == 1:
                        result[fid] = subforms[0]
                    else:
                        result[fid] = subforms
                        # raise RuntimeError('get_member_container_review: more than one subform found for {}'.format(fid))
            else:
                result[fid] = form_value

        return result

    def _get_repo_dict_item(self, key, title, in_dict, out_dict):
        if key not in in_dict:
            # print('_get_repo_dict_item: key {} not in {}'.format(key, in_dict))
            return
        item = in_dict[key]
        if item['app'].get('ftype', '') in ['Text', ]:
            out_dict[title] = {
                'Applicant Response': item['app']['data']
            }
        elif item['app'].get('ftype', '') in ['MultiChoice', ]:
            data = item['app']['data']
            if data is not None:
                result = []
                for idx, datum in enumerate(data):
                    result.append(datum)
                out_dict[title] = {
                    'Applicant Response': result
                }
        else:
            raise RuntimeError('_get_repo_dict_item: unknown ftype "{}"'.format(item))

        for rev_key in item.keys():
            if rev_key == 'app' or rev_key == 'key':
                continue
            rev_name = "Reviewer {}".format(rev_key)
            if  rev_key in item.keys():
                out_dict[title][rev_name] = item[rev_key]['data']

    def get_member_container_review(self):
        # cwd = os.getcwd()
        # app_spec = self._load_registry_app('{}/../../src/collective.jsonify/collective/jsonify/json.app.txt'.format(cwd))
        # org_spec = self._load_registry_app('{}/../../src/collective.jsonify/collective/jsonify/json.org.txt'.format(cwd))
        adict = {
            'organisation':  {},
            'version_and_state': {
                'application': {
                    'serial_number': "",
                    'created': "",
                    'modified': "",
                    'approved_date': "",
                    'type': "",
                },
                'review_state': {
                    'iteration': "",
                    'progress': "",
                    'review_state': [],
                },
            },
            # 'repository': {
            #     'repository_type': {},
            #     'repository_description': {},
            #     'repository_community': {},
            #     'level_performed': {},
            #     'partners': {},
            #     'changes': {},
            #     'other_info': {},
            # },
            'criteria':  [],
            'feedback':  {}
        }
        catalog = api.portal.get_tool("portal_catalog")
        # Prep - pull all relevant data
        organisation_prep = self._process_form_values(self.context['form_values'])
        prep_dict = {'application': {}, 'criteria': [], 'brain': []}
        for obj in self.context.values():
            if not hasattr(obj, 'portal_type'):
                print('get_member_container_review: no portal_type: {}'.format(obj.id))
                continue
            elif obj.portal_type == 'Application':
                # print('get_member_container_review: found application: {}'.format(obj.id))
                prep_dict['application'] = self._process_form_values(obj['form_values'])

                app_brain = catalog(UID=obj.UID())[0]
                adict['version_and_state']['review_state']['progress'] = app_brain.review_state
                adict['version_and_state']['application']['created'] = obj.CreationDate()[:10]
                adict['version_and_state']['application']['modified'] = obj.ModificationDate()[:10]
                if app_brain.review_state == 'approved':
                    adict['version_and_state']['application']['approved_date'] = str(app_brain.getApprovedDate)[:10]
                adict['version_and_state']['application']['serial_number'] = obj.UID()
                adict['version_and_state']['application']['type'] = app_brain.getReviewType

                for child in obj.values():
                    # print('get_member_container_review: found {}: {}'.format(child.id, child.portal_type))
                    if child.portal_type == 'Review':
                        prep_dict['criteria'].append(self._process_form_values(child['form_values']))
                        review_brain = catalog(UID=child.UID())[0]
                        adict['version_and_state']['review_state']['review_state'].append(review_brain.review_state)
            else:
                print('get_member_container_review: unprocessed portal_type: {}'.format(obj.portal_type))
                    
        # # Arrange output
        for key in organisation_prep.keys():
            if not organisation_prep[key].get('ftitle', False):
                print('get_member_container_review: ignore organaization no ftitle')
                continue
            if not organisation_prep[key].get('ftype', False):
                print('get_member_container_review: ignore organaization {} not ftype'.format(
                    organisation_prep[key]['ftitle']))
                continue
            if organisation_prep[key]['ftype'] in ['Pulldown', 'TextLine', 'Text']:
                title = organisation_prep[key].get('ftitle')
                adict['organisation'][title] = organisation_prep[key]['data']
            elif organisation_prep[key]['ftype'] in ['Description', 'Title', 'Empty']:
                pass
                # print('get_member_container_review: ignore organaization {} item {}'.format(
                #     organisation_prep[key]['ftype'],
                #     organisation_prep[key]['ftitle']))
            else:
                raise RuntimeError('Organization ftype {} unknown'.format(organisation[key]['ftype']))

        # Arrange data into criteria
        prep_dict_2 = {}
        prep_dict_3 = {}
        keys = prep_dict['application'].keys()
        keys.sort()
        for key in keys:
            # if not key.startswith('r'):
            #     continue
            # if not key[1].isdigit():
            #     continue
            # crit_num = key.split('_')[0]
            # if crit_num not in prep_dict_2.keys():
            #     prep_dict_2[crit_num] = {} 

            if key.startswith('r') and key[1].isdigit():
                crit_num = key.split('_')[0]
                if crit_num not in prep_dict_2.keys():
                    prep_dict_2[crit_num] = {}
                prep_dict_2[crit_num][key] = key_dict = {}
            else:
                if key not in prep_dict_3.keys():
                    prep_dict_3[key] = key_dict = {}
            key_dict['key'] = key
            key_dict['app'] = prep_dict['application'][key]
            for idx, criteria in enumerate(prep_dict['criteria']):
                key_dict[idx + 1] = criteria[key]
            
        # Arrange data into criteria
        crit_dict = {}
        keys = prep_dict_2.keys()
        keys.sort()
        for crit_num in keys:
            criterium = prep_dict_2[crit_num]
            crit_dict[crit_num] = key_dict = {}
            # key_dict['ToBeDeleted'] = criterium

            compliance_key = "{}_compliance".format(crit_num)
            if compliance_key in criterium.keys():
                key_dict['Compliance Level'] = {}
                item = criterium[compliance_key]['app']
                if item is not None:
                    if item.get('ftype', '') == 'Pulldown':
                        if item.get('data', ''):
                            key_dict['Compliance Level']['Applicant Claim'] = int(item['data'].split(' ')[0])
                    else:
                        raise RuntimeError('Applicant compliance level should only be a PullDown: {}'.format(item))
                        # key_dict['Compliance Level']['Comment'] = val
                for rev_key in criterium[compliance_key].keys():
                    if rev_key == 'app' or rev_key == 'key':
                        continue
                    rev_name = "Reviewer {}".format(rev_key)
                    if  rev_key in criterium[compliance_key].keys():
                        key_dict['Compliance Level'][rev_name] = {}
                        items = criterium[compliance_key][rev_key]
                        if type(items) != list:
                            items = [items]
                        for item in items:
                            data = item['data']
                            if data is not None:
                                if item['ftype'] == 'Pulldown':
                                    key_dict['Compliance Level'][rev_name]['Assessed Level'] = int(data.split(' ')[0])
                                else:
                                    key_dict['Compliance Level'][rev_name]['Comment'] = data

            repsonse_key = "{}_response".format(crit_num)
            if repsonse_key in criterium.keys():
                key_dict['Response'] = {
                    'Applicant Notes': criterium[repsonse_key]['app']['data']
                }
                for rev_key in criterium[repsonse_key].keys():
                    if rev_key == 'app' or rev_key == 'key':
                        continue
                    rev_name = "Reviewer {}".format(rev_key)
                    if  rev_key in criterium[repsonse_key].keys():
                        key_dict['Response'][rev_name] = criterium[repsonse_key][rev_key]['data']

        # Arrange data into repository info
        repo_dict = {}
        key = "repository_type"
        title = "Repository Type"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        key = "designated_community"
        title = "Brief Description of the Repositorys Designated Community"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        key = "type_comments"
        title = "Brief Description of Repository"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        key = "curation"
        title = "Level of Curation Performed"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        key = "curation_comments"
        title = "Comments on Level of Curation Performed"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        key = "outsource"
        title = "Insource/Outsource Partners"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        key = "other_info"
        title = "Other Relevant Information"
        self._get_repo_dict_item(key, title, prep_dict_3, repo_dict)

        # adict['prep_dict'] = prep_dict
        # adict['prep_dict_2'] = prep_dict_2
        # adict['prep_dict_3'] = prep_dict_3
        adict['repository_information'] = repo_dict
        if 'r17' in crit_dict:
            adict['feedback'] = crit_dict.pop('r17')['Response']
        if 'Applicant Notes' in adict['feedback']:
            adict['feedback']['Applicant Feedback'] = adict['feedback'].pop('Applicant Notes')
        if 'Reviewer 1' in adict['feedback']:
            adict['feedback']['Reviewer 1 Feedback'] = adict['feedback'].pop('Reviewer 1')
        if 'Reviewer 2' in adict['feedback']:
            adict['feedback']['Reviewer 2 Feedback'] = adict['feedback'].pop('Reviewer 2')
        if prep_dict.get('application') == {}:
            adict['version_and_state']['application'] = None
        else:
            adict['criteria'] = crit_dict
        self['reviews'] = adict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from concepts.models import Concept
from oclapi.models import BaseModel, ACCESS_TYPE_EDIT, ACCESS_TYPE_VIEW, ResourceVersionModel
from sources.models import Source, SourceVersion
from django.db.models import get_model

MAPPING_RESOURCE_TYPE = 'Mapping'
MAPPING_VERSION_RESOURCE_TYPE = 'MappingVersion'

class Mapping(BaseModel):
    parent = models.ForeignKey(Source, related_name='mappings_from')
    map_type = models.TextField()
    from_concept = models.ForeignKey(Concept, related_name='mappings_from')
    to_concept = models.ForeignKey(Concept, null=True, blank=True, related_name='mappings_to', db_index=False)
    to_source = models.ForeignKey(Source, null=True, blank=True, related_name='mappings_to', db_index=False)
    to_concept_code = models.TextField(null=True, blank=True)
    to_concept_name = models.TextField(null=True, blank=True)
    retired = models.BooleanField(default=False)
    external_id = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = (
            ("parent", "map_type", "from_concept", "to_concept", "to_source", "to_concept_code"),
        )

    def clean(self, exclude=None):
        messages = []
        try:
            if self.from_concept == self.to_concept:
                messages.append("Cannot map concept to itself.")
        except Concept.DoesNotExist:
            messages.append("Must specify a 'from_concept'.")
        if not (self.to_concept or (self.to_source and self.to_concept_code)):
            messages.append("Must specify either 'to_concept' or 'to_source' & 'to_concept_code")
        if self.to_concept and (self.to_source or self.to_concept_code):
            messages.append("Must specify either 'to_concept' or 'to_source' & 'to_concept_code'. Cannot specify both.")
        if messages:
            raise ValidationError(' '.join(messages))

    def clone(self, user):
        return Mapping(
            created_by=user,
            public_access=self.public_access,
            extras=self.extras,
            parent_id=self.parent_id,
            map_type=self.map_type,
            from_concept=self.from_concept,
            to_concept=self.to_concept,
            to_source=self.to_source,
            to_concept_code=self.to_concept_code,
            to_concept_name=self.to_concept_name,
            retired=self.retired,
            external_id=self.external_id,
        )

    @property
    def mnemonic(self):
        return self.id

    @property
    def source(self):
        return self.parent.mnemonic

    @property
    def owner(self):
        return self.parent.owner_name

    @property
    def owner_type(self):
        return self.parent.owner_type

    @property
    def from_source(self):
        return self.from_concept.parent

    @property
    def from_source_owner(self):
        return self.from_source.owner_name

    @property
    def from_source_owner_mnemonic(self):
        return self.from_source.owner.mnemonic

    @property
    def from_source_owner_type(self):
        return self.from_source.owner_type

    @property
    def from_source_name(self):
        return self.from_source.mnemonic

    @property
    def from_source_url(self):
        self.from_source.url

    @property
    def from_source_shorthand(self):
        return "%s:%s" % (self.from_source_owner_mnemonic, self.from_source_name)

    @property
    def from_concept_code(self):
        return self.from_concept.mnemonic

    @property
    def from_concept_name(self):
        return self.from_concept.display_name

    @property
    def from_concept_url(self):
        return self.from_concept.url

    @property
    def from_concept_shorthand(self):
        return "%s:%s" % (self.from_source_shorthand, self.from_concept_code)

    def get_to_source(self):
        return self.to_source or self.to_concept and self.to_concept.parent

    @property
    def to_source_name(self):
        return self.get_to_source() and self.get_to_source().mnemonic

    @property
    def to_source_url(self):
        to_source = self.get_to_source()
        return to_source.url if to_source else None

    @property
    def to_source_owner(self):
        return self.get_to_source() and unicode(self.get_to_source().parent)

    @property
    def to_source_owner_mnemonic(self):
        return self.get_to_source() and self.get_to_source().owner.mnemonic

    @property
    def to_source_owner_type(self):
        return self.get_to_source() and self.get_to_source().owner_type

    @property
    def to_source_shorthand(self):
        return self.get_to_source() and "%s:%s" % (self.to_source_owner_mnemonic, self.to_source_name)

    def get_to_concept_name(self):
        return self.to_concept_name or (self.to_concept and self.to_concept.display_name)

    def get_to_concept_code(self):
        return self.to_concept_code or (self.to_concept and self.to_concept.mnemonic)

    @property
    def to_concept_url(self):
        return self.to_concept.url if self.to_concept else None

    @property
    def to_concept_shorthand(self):
        return self.to_source_shorthand and self.to_concept_code and "%s:%s" % (self.to_source_shorthand, self.to_concept_code)

    @property
    def public_can_view(self):
        return self.public_access in [ACCESS_TYPE_EDIT, ACCESS_TYPE_VIEW]

    @staticmethod
    def resource_type():
        return MAPPING_RESOURCE_TYPE

    @staticmethod
    def get_url_kwarg():
        return 'mapping'

    @property
    def get_latest_version(self):
        return MappingVersion.objects.filter(versioned_object_id=self.id).order_by('-created_at')[:1][0]

    @classmethod
    def retire(cls, obj, updated_by, **kwargs):
        if obj.retired:
            return False
        obj.retired = True
        obj.updated_by = updated_by
        obj.save(**kwargs)
        return True

    @classmethod
    def persist_changes(cls, obj, updated_by, update_comment=None, **kwargs):
        errors = dict()
        obj.updated_by = updated_by
        try:
            if obj.to_source == None:
                obj._meta.unique_together = (
                    ("parent", "map_type", "from_concept", "to_concept"),
                )
            else:
                obj._meta.unique_together = (
                    ("parent", "map_type", "from_concept", "to_source", "to_concept_code"),
                )
            obj.full_clean()
        except ValidationError as e:
            errors.update(e.message_dict)
            return errors

        persisted = False
        try:
            source_version = SourceVersion.get_head_of(obj.parent)
            obj.save(**kwargs)

            prev_latest_version = MappingVersion.objects.get(versioned_object_id=obj.id, is_latest_version=True);
            prev_latest_version.is_latest_version = False

            new_latest_version  = MappingVersion.for_mapping(obj)
            new_latest_version.previous_version = prev_latest_version
            new_latest_version.update_comment = update_comment
            new_latest_version.mnemonic = int(prev_latest_version.mnemonic) + 1
            new_latest_version.save()

            source_version.update_mapping_version(new_latest_version)
            prev_latest_version.save()


            persisted = True
        finally:
            if not persisted:
                errors['non_field_errors'] = ["Failed to persist mapping."]
        return errors

    @classmethod
    def persist_new(cls, obj, created_by, **kwargs):
        errors = dict()
        non_field_errors = []

        # Check for required fields
        if not created_by:
            non_field_errors.append('Must specify a creator')
        parent_resource = kwargs.pop('parent_resource', None)
        if not parent_resource:
            non_field_errors.append('Must specify a parent source')
        if non_field_errors:
            errors['non_field_errors'] = non_field_errors
            return errors

        # Populate required fields and validate
        obj.created_by = created_by
        obj.updated_by = created_by
        obj.parent = parent_resource
        obj.public_access = parent_resource.public_access
        try:
            if obj.to_source == None:
                obj._meta.unique_together = (
                    ("parent", "map_type", "from_concept", "to_concept"),
                )
            else:
                obj._meta.unique_together = (
                    ("parent", "map_type", "from_concept", "to_source", "to_concept_code"),
                )
            obj.full_clean()
        except ValidationError as e:
            errors.update(e.message_dict)
            return errors

        # Get the parent source version and its initial list of mappings IDs
        parent_resource_version = kwargs.pop('parent_resource_version', None)
        if parent_resource_version is None:
            parent_resource_version = parent_resource.get_version_model().get_head_of(parent_resource)
        child_list_attribute = kwargs.pop('mapping_list_attribute', 'mappings')
        initial_parent_children = getattr(parent_resource_version, child_list_attribute) or []

        errored_action = 'saving mapping'
        persisted = False
        initial_version=None
        try:
            obj.save(**kwargs)
            #mapping version save start
            initial_version = MappingVersion.for_mapping(obj)
            initial_version.mnemonic = 1
            initial_version.save()
            # update URL
            obj.save()
            # mapping version save end
            # Add the mapping to its parent source version
            errored_action = 'associating mapping with parent resource'
            parent_children = getattr(parent_resource_version, child_list_attribute) or []
            parent_children.append(initial_version.id)
            setattr(parent_resource_version, child_list_attribute, parent_children)
            parent_resource_version.save()

            # Save the mapping again to trigger the Solr update
            errored_action = 'saving mapping to trigger Solr update'
            initial_version.save()
            persisted = True
        finally:
            if not persisted:
                errors['non_field_errors'] = ['An error occurred while %s.' % errored_action]
                setattr(parent_resource_version, child_list_attribute, initial_parent_children)
                parent_resource_version.save()
                if obj.id:
                    obj.delete()
                if initial_version and initial_version.id:
                    initial_version.delete()
        return errors

    @classmethod
    def diff(cls, v1, v2):
        diffs = {}
        if v1.public_access != v2.public_access:
            diffs['public_access'] = {'was': v1.public_access, 'is': v2.public_access}
        if v1.map_type != v2.map_type:
            diffs['map_type'] = {'was': v1.map_type, 'is': v2.map_type}
        if v1.from_concept != v2.from_concept:
            diffs['from_concept'] = {'was': v1.from_concept, 'is': v2.from_concept}
        if v1.to_concept != v2.to_concept:
            diffs['to_concept'] = {'was': v1.to_concept, 'is': v2.to_concept}
        if v1.to_source != v2.to_source:
            diffs['to_source'] = {'was': v1.to_source, 'is': v2.to_source}
        if v1.to_concept_code != v2.to_concept_code:
            diffs['to_concept_code'] = {'was': v1.to_concept_code, 'is': v2.to_concept_code}
        if v1.to_concept_name != v2.to_concept_name:
            diffs['to_concept_name'] = {'was': v1.to_concept_name, 'is': v2.to_concept_name}

        # Diff extras
        extras1 = v1.extras or {}
        extras2 = v2.extras or {}
        diff = len(extras1) != len(extras2)
        if not diff:
            for key in extras1:
                if key not in extras2:
                    diff = True
                    break
                if extras2[key] != extras1[key]:
                    diff = True
                    break
        if diff:
            diffs['extras'] = {'was': extras1, 'is': extras2}

        return diffs


class MappingVersion(ResourceVersionModel):
    parent = models.ForeignKey(Source, related_name='mappings_version_from')
    map_type = models.TextField()
    from_concept = models.ForeignKey(Concept, related_name='mappings_version_from')
    to_concept = models.ForeignKey(Concept, null=True, blank=True, related_name='mappings_version_to', db_index=False)
    to_source = models.ForeignKey(Source, null=True, blank=True, related_name='mappings_version_to', db_index=False)
    to_concept_code = models.TextField(null=True, blank=True)
    to_concept_name = models.TextField(null=True, blank=True)
    retired = models.BooleanField(default=False)
    external_id = models.TextField(null=True, blank=True)
    is_latest_version = models.BooleanField(default=True)
    update_comment = models.TextField(null=True, blank=True)

    class Meta:
        pass

    @property
    def source(self):
        return self.parent.mnemonic

    @property
    def owner(self):
        return self.parent.owner_name

    @property
    def owner_type(self):
        return self.parent.owner_type

    @property
    def from_source(self):
        return self.from_concept.parent

    @property
    def from_source_owner(self):
        return self.from_source.owner_name

    @property
    def from_source_owner_mnemonic(self):
        return self.from_source.owner.mnemonic

    @property
    def from_source_owner_type(self):
        return self.from_source.owner_type

    @property
    def from_source_name(self):
        return self.from_source.mnemonic

    @property
    def from_source_url(self):
        self.from_source.url

    @property
    def from_source_shorthand(self):
        return "%s:%s" % (self.from_source_owner_mnemonic, self.from_source_name)

    @property
    def from_concept_code(self):
        return self.from_concept.mnemonic

    @property
    def from_concept_name(self):
        return self.from_concept.display_name

    @property
    def from_concept_url(self):
        return self.from_concept.url

    @property
    def from_concept_shorthand(self):
        return "%s:%s" % (self.from_source_shorthand, self.from_concept_code)

    def get_to_source(self):
        return self.to_source or self.to_concept and self.to_concept.parent

    @property
    def to_source_name(self):
        return self.get_to_source() and self.get_to_source().mnemonic

    @property
    def to_source_url(self):
        to_source = self.get_to_source()
        return to_source.url if to_source else None

    @property
    def to_mapping_url(self):
        return self.versioned_object.uri

    @property
    def to_source_owner(self):
        return self.get_to_source() and unicode(self.get_to_source().parent)

    @property
    def to_source_owner_mnemonic(self):
        return self.get_to_source() and self.get_to_source().owner.mnemonic

    @property
    def to_source_owner_type(self):
        return self.get_to_source() and self.get_to_source().owner_type

    @property
    def to_source_shorthand(self):
        return self.get_to_source() and "%s:%s" % (self.to_source_owner_mnemonic, self.to_source_name)

    def get_to_concept_name(self):
        return self.to_concept_name or (self.to_concept and self.to_concept.display_name)

    def get_to_concept_code(self):
        return self.to_concept_code or (self.to_concept and self.to_concept.mnemonic)

    @property
    def to_concept_url(self):
        return self.to_concept.url if self.to_concept else None

    @property
    def to_concept_shorthand(self):
        return self.to_source_shorthand and self.to_concept_code and "%s:%s" % (
        self.to_source_shorthand, self.to_concept_code)

    @property
    def public_can_view(self):
        return self.public_access in [ACCESS_TYPE_EDIT, ACCESS_TYPE_VIEW]

    @staticmethod
    def resource_type():
        return MAPPING_VERSION_RESOURCE_TYPE

    @property
    def collection_versions(self):
        return get_model('collection', 'CollectionVersion').objects.filter(mappings=self.id)

    @staticmethod
    def get_url_kwarg():
        return 'mapping_version'

    @classmethod
    def for_mapping(cls, mapping, previous_version=None, parent_version=None):
        return MappingVersion(
            public_access=mapping.public_access,
            is_active=True,
            parent=mapping.parent,
            map_type=mapping.map_type,
            from_concept=mapping.from_concept,
            to_concept=mapping.to_concept,
            to_source=mapping.to_source,
            to_concept_code=mapping.to_concept_code,
            to_concept_name=mapping.to_concept_name,
            retired=mapping.retired,
            external_id=mapping.external_id,
            versioned_object_id=mapping.id,
            versioned_object_type=ContentType.objects.get_for_model(Mapping),
            released=False,
            previous_version=previous_version,
            parent_version=parent_version,
            created_by=mapping.created_by,
            updated_by=mapping.updated_by
        )

    @classmethod
    def get_latest_version_by_id(cls, id):
        versions = MappingVersion.objects.filter(versioned_object_id=id, is_latest_version=True).order_by('-created_at')
        return versions[0] if versions else None


@receiver(post_save, sender=Source)
def propagate_parent_attributes(sender, instance=None, created=False, **kwargs):
    if created:
        return
    for mapping in Mapping.objects.filter(parent_id=instance.id):
        update_index = False
        if mapping.is_active != instance.is_active:
            update_index = True
            mapping.is_active = instance.is_active
        if mapping.public_access != instance.public_access:
            update_index |= True
            mapping.public_access = instance.public_access
        if update_index:
            for mapping_version in MappingVersion.objects.filter(versioned_object_id=mapping.id):
                mapping_version.is_active = instance.is_active
                mapping_version.public_access = instance.public_access
                mapping_version.save()
            mapping.save()


@receiver(post_save, sender=Source)
def propagate_owner_status(sender, instance=None, created=False, **kwargs):
    if created:
        return
    for mapping in Mapping.objects.filter(parent_id=instance.id):
        if (instance.is_active and not mapping.is_active) or (mapping.is_active and not instance.is_active):
            mapping.save()

# PyTrackDat is a utility for assisting in online database creation.
# Copyright (C) 2018-2019 the PyTrackDat authors.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Contact information:
#     David Lougheed (david.lougheed@gmail.com)

import csv
import datetime
import getpass
import gzip
import importlib
import io
import os
import pprint
import shutil
import subprocess
import sys


from typing import Dict, IO, List, Optional, Tuple, Union

from .common import *

ADMIN_FILE_HEADER = """# Generated using PyTrackDat v{}
from django.contrib import admin
from advanced_filters.admin import AdminAdvancedFiltersMixin

from core.models import *
from .export_csv import ExportCSVMixin
from .import_csv import ImportCSVMixin
from .export_labels import ExportLabelsMixin

""".format(VERSION)

SNAPSHOT_ADMIN_FILE = """# Generated using PyTrackDat v{}
from django.contrib import admin
from django.utils.html import format_html
from advanced_filters.admin import AdminAdvancedFiltersMixin

from snapshot_manager.models import *


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    exclude = ('snapshot_type', 'size', 'name', 'reason')
    list_display = ('__str__', 'download_link', 'reason')

    def download_link(self, obj):
        return format_html('<a href="{{url}}">Download Database Snapshot</a>',
                           url='/snapshots/' + str(obj.pk) + '/download/')
        
    download_link.short_description = 'Download Link'

""".format(VERSION)

MODELS_FILE_HEADER = """# Generated using PyTrackDat v{version}
from {models_path} import models

"""

MODEL_TEMPLATE = """class {name}(models.Model):
    @classmethod
    def ptd_info(cls):
        return {fields}

    @classmethod
    def get_label_name(cls):
        return '{label_name}'

    @classmethod
    def get_id_type(cls):
        return '{id_type}'

    class Meta:
        verbose_name = '{verbose_name}'

    pdt_created_at = models.DateTimeField(auto_now_add=True, null=False)
    pdt_modified_at = models.DateTimeField(auto_now=True, null=False)"""

SNAPSHOT_MODEL = """import os
import shutil
from datetime import datetime

import {site_name}.settings as settings

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.http import HttpResponse, Http404


class Snapshot(models.Model):
    pdt_created_at = models.DateTimeField(auto_now_add=True, null=False)
    pdt_modified_at = models.DateTimeField(auto_now=True, null=False)
    snapshot_type = models.TextField(help_text='Created by whom?', max_length=6, default='manual',
                                     choices=(('auto', 'Automatic'), ('manual', 'Manual')), null=False, blank=False)
    name = models.TextField(help_text='Name of snapshot file', max_length=127, null=False, blank=False)
    reason = models.TextField(help_text='Reason for snapshot creation', max_length=127, null=False, blank=True,
                              default='Manually created')
    size = models.IntegerField(help_text='Size of database (in bytes)', null=False)

    def __str__(self):
        return self.snapshot_type + " snapshot (" + str(self.name) + "; size: " + str(self.size) + " bytes)"

    def save(self, *args, **kwargs):
        if not self.pk:
            with transaction.atomic():
                # TODO: THIS ONLY WORKS WITH SQLITE
                # Newly-created snapshot

                name = "snapshot-" + str(datetime.utcnow()).replace(" ", "_").replace(":", "-") + ".sqlite3"

                shutil.copyfile(settings.DATABASES['default']['NAME'],
                                os.path.join(settings.BASE_DIR, "snapshots", name))

                self.name = name
                self.size = os.path.getsize(os.path.join(settings.BASE_DIR, "snapshots", name))

        super(Snapshot, self).save(*args, **kwargs)


@receiver(pre_delete, sender=Snapshot)
def delete_snapshot_file(sender, instance, **kwargs):
    try:
        os.remove(os.path.join(settings.BASE_DIR, "snapshots", instance.name))
    except OSError:
        print("Error deleting snapshot")
        # TODO: prevent deletion in some way?


@login_required
def download_view(request, id):
    try:
        snapshot = Snapshot.objects.get(pk=id)
        path = os.path.join(settings.BASE_DIR, 'snapshots', snapshot.name)
        if os.path.exists(path):
            # TODO
            with open(path, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/x-sqlite3')
                response['Content-Disposition'] = 'inline; filename=' + snapshot.name
                return response
        else:
            raise Http404('Snapshot file does not exist (database inconsistency!)')
        
    except Snapshot.DoesNotExist:
        raise Http404('Snapshot does not exist')

"""

API_FILE_HEADER = """# Generated using PyTrackDat v{version}

from rest_framework import serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from core.models import *
from snapshot_manager.models import Snapshot

api_router = DefaultRouter()


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Snapshot
        fields = ['pdt_created_at', 'pdt_modified_at', 'snapshot_type', 'name', 'reason', 'size']


class SnapshotViewSet(viewsets.ModelViewSet):
    queryset = Snapshot.objects.all()
    serializer_class = SnapshotSerializer
    
    
api_router.register(r'snapshots', SnapshotViewSet)


class MetaViewSet(viewsets.ViewSet):
    def list(self, _request):
        return Response({{
            "site_name": "{site_name}",
            "gis_mode": {gis_mode},
            "relations": {relations}
        }})


api_router.register(r'meta', MetaViewSet, basename='meta')


"""

URL_OLD = """urlpatterns = [
    path('admin/', admin.site.urls),
]"""
URL_NEW = """from django.urls import include

from core.api import api_router
from snapshot_manager.models import download_view

urlpatterns = [
    path('', admin.site.urls),
    path('api/', include(api_router.urls)),
    path('snapshots/<int:id>/download/', download_view, name='snapshot-download'),
    path('advanced_filters/', include('advanced_filters.urls')),
]"""

DEBUG_OLD = "DEBUG = True"
DEBUG_NEW = "DEBUG = not (os.getenv('DJANGO_ENV') == 'production')"

ALLOWED_HOSTS_OLD = "ALLOWED_HOSTS = []"
ALLOWED_HOSTS_NEW = "ALLOWED_HOSTS = ['127.0.0.1', '{}'] if (os.getenv('DJANGO_ENV') == 'production') else []"

INSTALLED_APPS_OLD = """INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]"""

INSTALLED_APPS_NEW = """INSTALLED_APPS = [
    'core.apps.CoreConfig',
    'snapshot_manager.apps.SnapshotManagerConfig',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'advanced_filters',
    'rest_framework',
]"""

INSTALLED_APPS_NEW_GIS = INSTALLED_APPS_NEW.replace(
    "'django.contrib.staticfiles',",
    """'django.contrib.staticfiles',

    'django.contrib.gis',"""
)

STATIC_OLD = "STATIC_URL = '/static/'"
STATIC_NEW = """STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')"""

REST_FRAMEWORK_SETTINGS = """
REST_FRAMEWORK = {'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated']}
"""

SPATIALITE_SETTINGS = """
SPATIALITE_LIBRARY_PATH='{}' if (os.getenv('DJANGO_ENV') != 'production') else None
"""

DATABASE_ENGINE_NORMAL = "django.db.backends.sqlite3"
DATABASE_ENGINE_GIS = "django.contrib.gis.db.backends.spatialite"

DISABLE_MAX_FIELDS = "\nDATA_UPLOAD_MAX_NUMBER_FIELDS = None\n"

BASIC_NUMBER_TYPES = {
    "integer": "IntegerField",
    "float": "FloatField",
}


class GenerationError(Exception):
    pass


def clean_field_help_text(d: str) -> str:
    return d.replace("\\", "\\\\").replace("'", "\\'")


def auto_key_formatter(f: Dict) -> str:
    return "models.AutoField(primary_key=True, help_text='{}')".format(clean_field_help_text(f["description"]))


def manual_key_formatter(f: Dict) -> str:
    # TODO: Shouldn't be always text?
    return "models.CharField(primary_key=True, max_length=127, " \
           "help_text='{}')".format(clean_field_help_text(f["description"]))


def foreign_key_formatter(f: Dict) -> str:
    return "models.ForeignKey('{}', help_text='{}', on_delete=models.CASCADE)".format(
        to_relation_name(f["additional_fields"][0]),
        f["description"].replace("'", "\\'")
    )


def basic_number_formatter(f: Dict) -> str:
    t = BASIC_NUMBER_TYPES[f["data_type"]]
    return "models.{}(help_text='{}', null={}{})".format(
        t,
        clean_field_help_text(f["description"]),
        str(f["nullable"]),
        "" if f["default"] is None else ", default={}".format(f["default"])
    )


def decimal_formatter(f: Dict) -> str:
    return "models.DecimalField(help_text='{}', max_digits={}, decimal_places={}, null={}{})".format(
        clean_field_help_text(f["description"]),
        f["additional_fields"][0],
        f["additional_fields"][1],
        str(f["nullable"]),
        "" if f["default"] is None else ", default=Decimal({})".format(f["default"])
    )


def boolean_formatter(f: Dict) -> str:
    return "models.BooleanField(help_text='{}', null={}{})".format(
        clean_field_help_text(f["description"]),
        str(f["nullable"]),
        "" if f["default"] is None else ", default={}".format(f["default"])
    )


def get_choices_from_text_field(f: Dict) -> Optional[Tuple[str]]:
    if len(f["additional_fields"]) == 2:
        # TODO: Choice human names
        choice_names = [str(c).strip() for c in f["additional_fields"][1].split(";") if str(c).strip() != ""]
        if len(choice_names) == 0:
            return None
        return tuple(choice_names)
    return None


def text_formatter(f: Dict) -> str:
    choices = ()
    max_length = None

    if len(f["additional_fields"]) >= 1:
        try:
            max_length = int(f["additional_fields"][0])
        except ValueError:
            pass

    if len(f["additional_fields"]) == 2:
        # TODO: Choice human names
        choice_names = get_choices_from_text_field(f)
        if choice_names is not None:
            choices = tuple(zip(choice_names, choice_names))

    return "models.{}(help_text='{}'{}{}{})".format(
        "TextField" if max_length is None else "CharField",
        clean_field_help_text(f["description"]),
        "" if f["default"] is None else ", default='{}'".format(f["default"]),  # TODO: Make sure default is cleaned
        "" if len(choices) == 0 else ", choices={}".format(str(choices)),
        "" if max_length is None else ", max_length={}".format(max_length)
    )


def date_formatter(f: Dict) -> str:
    # TODO: standardize date formatting... I think this might already be standardized?
    return "models.DateField(help_text='{}', null={}{})".format(
        clean_field_help_text(f["description"]),
        str(f["nullable"]),
        "" if f["default"] is None else ", default=datetime.strptime('{}', '%Y-%m-%d')".format(
            f["default"].strftime("%Y-%m-%d")
        )
    )


# All spatial fields cannot be null.


def point_formatter(f: Dict) -> str:
    # TODO: WARN IF NULLABLE
    # TODO: DO WE EVER MAKE THIS BLANK?
    # TODO: FIGURE OUT POINT FORMAT FOR DEFAULTS / IN GENERAL
    return "models.PointField(help_text='{}')".format(f["description"].replace("'", "\\'"))


def line_string_formatter(f: Dict) -> str:
    # TODO: WARN IF NULLABLE
    # TODO: DO WE EVER MAKE THIS BLANK?
    # TODO: FIGURE OUT LINE STRING FORMAT FOR DEFAULTS / IN GENERAL
    return "models.LineStringField(help_text='{}')".format(f["description"].replace("'", "\\'"))


def polygon_formatter(f: Dict) -> str:
    # TODO: WARN IF NULLABLE
    # TODO: DO WE EVER MAKE THIS BLANK?
    # TODO: FIGURE OUT POLYGON FORMAT FOR DEFAULTS / IN GENERAL
    return "models.PolygonField(help_text='{}')".format(f["description"].replace("'", "\\'"))


def multi_point_formatter(f: Dict) -> str:
    # TODO: WARN IF NULLABLE
    # TODO: DO WE EVER MAKE THIS BLANK?
    # TODO: FIGURE OUT POINT FORMAT FOR DEFAULTS / IN GENERAL
    return "models.MultiPointField(help_text='{}')".format(f["description"].replace("'", "\\'"))


def multi_line_string_formatter(f: Dict) -> str:
    # TODO: WARN IF NULLABLE
    # TODO: DO WE EVER MAKE THIS BLANK?
    # TODO: FIGURE OUT LINE STRING FORMAT FOR DEFAULTS / IN GENERAL
    return "models.MultiLineStringField(help_text='{}')".format(f["description"].replace("'", "\\'"))


def multi_polygon_formatter(f: Dict) -> str:
    # TODO: WARN IF NULLABLE
    # TODO: DO WE EVER MAKE THIS BLANK?
    # TODO: FIGURE OUT POLYGON FORMAT FOR DEFAULTS / IN GENERAL
    return "models.MultiPolygonField(help_text='{}')".format(f["description"].replace("'", "\\'"))


DJANGO_TYPE_FORMATTERS = {
    # Standard PyTrackDat Fields
    "auto key": auto_key_formatter,
    "manual key": manual_key_formatter,
    "foreign key": foreign_key_formatter,
    "integer": basic_number_formatter,
    "decimal": decimal_formatter,
    "float": basic_number_formatter,
    "boolean": boolean_formatter,
    "text": text_formatter,
    "date": date_formatter,

    # PyTrackDat GeoDjango Fields
    "point": point_formatter,
    "line string": line_string_formatter,
    "polygon": polygon_formatter,
    "multi point": multi_point_formatter,
    "multi line string": multi_line_string_formatter,
    "multi polygon": multi_polygon_formatter,
    
    "unknown": text_formatter  # Default to text fields... TODO: Should give a warning
}


def get_default_from_csv_with_type(field_name: str, dv: str, dt: str, nullable=False, null_values=()) \
        -> Union[None, int, datetime.datetime, str, bool]:
    if dv.strip() == "" and dt != "boolean":
        return None

    if dt == "integer":
        return int(dv)

    if dt == "date":
        # TODO: adjust format based on heuristics
        # TODO: Allow extra column setting with date format from python docs?
        if re.match(RE_DATE_YMD_D, dv):
            return datetime.strptime(dv, "%Y-%m-%d")
        elif re.match(RE_DATE_DMY_D, dv):
            # TODO: ambiguous d-m-Y or m-d-Y
            print("Warning: Assuming d-m-Y date format for ambiguously-formatted date field '{}'.".format(field_name))
            return datetime.strptime(dv, "%d-%m-%Y", str_v)
        else:
            # TODO: Warning
            print("Warning: Default value '{}' the date-typed field '{}' does not match any "
                  "PyTrackDat-compatible formats.".format(dv, field_name))
            return None

    if dt == "time":
        # TODO: adjust format based on MORE heuristics
        # TODO: Allow extra column setting with time format from python docs?
        if len(dv.split(":")) == 2:
            return datetime.strptime(dv, "%H:%M")
        else:
            return datetime.strptime(dv, "%H:%M:%S")

    if dt == "boolean":
        if nullable and ((len(null_values) != 0 and dv.strip() in null_values) or (dv.strip() == "")):
            return None

        return dv.lower() in ("y", "yes", "t", "true")

    return dv


def design_to_relation_fields(df: IO, gis_mode: bool) -> List[Dict]:
    """
    Validates the design file into relations and their fields.
    """

    relations = []

    design_reader = csv.reader(df)
    relation_name = next(design_reader)

    end_loop = False

    while not end_loop:
        python_relation_name = to_relation_name(relation_name[0])
        python_relation_name_lower = field_to_py_code(relation_name[0])

        relation_fields = []
        id_type = ""

        end_inner_loop = False

        while not end_inner_loop:
            try:
                current_field = next(design_reader)
                while current_field and "".join(current_field).strip() != "":
                    # TODO: Process

                    field_name = field_to_py_code(current_field[1])
                    data_type = standardize_data_type(current_field[2])

                    if not valid_data_type(data_type, gis_mode):
                        raise GenerationError("Error: Unknown data type specified for field '{}': '{}'.".format(
                            field_name,
                            data_type
                        ))

                    nullable = current_field[3].strip().lower() in ("true", "t", "yes", "y", "1")
                    null_values = tuple([n.strip() for n in current_field[4].split(";")])

                    if data_type in ("auto key", "manual key") and id_type != "":
                        raise GenerationError(
                            "Error: More than one primary key (auto/manual key) was specified for relation '{}'. "
                            "Please only specify one primary key.".format(python_relation_name)
                        )

                    if data_type == "auto key":
                        id_type = "integer"
                    elif data_type == "manual key":
                        id_type = "text"

                    # TODO: This handling of additional_fields could eventually cause trouble, because it can shift
                    #  positions of additional fields if a blank additional field occurs before a valued one.
                    current_field_data = {
                        "name": field_name,
                        "csv_name": current_field[0],
                        "data_type": data_type,
                        "nullable": nullable,
                        "null_values": null_values,
                        "default": get_default_from_csv_with_type(field_name, current_field[5].strip(), data_type,
                                                                  nullable, null_values),
                        "description": current_field[6].strip(),
                        "additional_fields": [f for f in current_field[7:] if f.strip() != ""]
                    }

                    if (len(current_field_data["additional_fields"]) >
                            len(DATA_TYPE_ADDITIONAL_DESIGN_SETTINGS[data_type])):
                        print(
                            "Warning: More additional settings specified for field '{}' than can be used.\n"
                            "         Available settings: '{}' \n".format(
                                field_name,
                                "', '".join(DATA_TYPE_ADDITIONAL_DESIGN_SETTINGS[data_type])
                            )
                        )

                    if data_type == "text":
                        choices = get_choices_from_text_field(current_field_data)
                        if choices is not None and current_field[5].strip() != "" and \
                                current_field[5].strip() not in choices:
                            raise GenerationError(
                                "Error: Default value for field '{}' in relation '{}' does not match any available "
                                "       choices for the field. Available choices: {}".format(
                                    current_field[1],
                                    python_relation_name,
                                    ", ".join(choices)
                                ))

                        if choices is not None and len(choices) > 1:
                            current_field_data["choices"] = choices

                    relation_fields.append(current_field_data)

                    current_field = next(design_reader)

            except StopIteration:
                if len(relation_fields) == 0:
                    end_loop = True
                    break

                # Otherwise, save the relation information.

            relations.append({
                "name": python_relation_name,
                "name_lower": python_relation_name_lower,
                "fields": relation_fields,
                "id_type": id_type
            })

            # Find the next relation.

            relation_name = ""

            try:
                while not relation_name or "".join(relation_name).strip() == "":
                    rel = next(design_reader)
                    if len(rel) > 0:
                        relation_name = rel
                        end_inner_loop = True

            except StopIteration:
                end_loop = True
                break

    return relations


def create_admin(relations: List[Dict], site_name: str, gis_mode: bool) -> io.StringIO:
    """
    Creates the contents of the admin.py file for the Django data application.
    """

    af = io.StringIO()

    af.write(ADMIN_FILE_HEADER)
    af.write("admin.site.site_header = 'PyTrackDat: {}'\n\n".format(site_name))

    for relation in relations:
        # Write admin information

        af.write("\n\n@admin.register({})\n".format(relation["name"]))
        af.write("class {}Admin(ExportCSVMixin, ImportCSVMixin, ExportLabelsMixin, AdminAdvancedFiltersMixin, "
                 "admin.ModelAdmin):\n".format(relation["name"]))
        af.write("    change_list_template = 'admin/core/change_list.html'\n")
        af.write("    actions = ['export_csv', 'export_labels']\n")

        # TODO: Improve this to show all length-limited text fields
        list_display_fields = [r["name"] for r in relation["fields"]
                               if r["data_type"] not in ("text", "auto key", "manual key") or "choices" in r]
        key = [r["name"] for r in relation["fields"] if r["data_type"] in ("auto key", "manual key")]
        list_display_fields = key + list_display_fields

        list_filter_fields = [r["name"] for r in relation["fields"]
                              if r["data_type"] in ("boolean",) or "choices" in r]

        advanced_filter_fields = [r["name"] for r in relation["fields"]]

        if len(list_display_fields) > 1:
            af.write("    list_display = ('{}',)\n".format("', '".join(list_display_fields)))

        if len(list_filter_fields) > 0:
            af.write("    list_filter = ('{}',)\n".format("', '".join(list_filter_fields)))

        if len(advanced_filter_fields) > 0:
            af.write("    advanced_filter_fields = ('{}',)\n".format("', '".join(advanced_filter_fields)))

        af.flush()

    af.seek(0)

    return af


def create_models(relations: List[Dict], gis_mode: bool) -> io.StringIO:
    """
    Creates the contents of the model.py file for the Django data application.
    """

    mf = io.StringIO()

    mf.write(MODELS_FILE_HEADER.format(version=VERSION,
                                       models_path="django.contrib.gis.db" if gis_mode else "django.db"))

    for relation in relations:
        mf.write("\n\n")
        mf.write(MODEL_TEMPLATE.format(
            name=relation["name"],
            fields=pprint.pformat(relation["fields"], indent=12, width=120, compact=True),
            label_name=relation["name"][len(PDT_RELATION_PREFIX):],
            id_type=relation["id_type"],
            verbose_name=relation["name"][len(PDT_RELATION_PREFIX):]
        ))
        mf.write("\n\n")

        for f in relation["fields"]:
            mf.write("    {} = {}\n".format(f["name"], DJANGO_TYPE_FORMATTERS[f["data_type"]](f)))

        mf.flush()

    mf.seek(0)

    return mf


def create_api(relations: List[Dict], site_name: str, gis_mode: bool) -> io.StringIO:
    """
    Creates the contents of the API specification file.
    """

    api_file = io.StringIO()

    api_file.write(API_FILE_HEADER.format(version=VERSION, site_name=site_name, gis_mode=gis_mode,
                                          relations=pprint.pformat(relations, indent=12, width=120, compact=True)))

    for relation in relations:
        api_file.write("\n")
        api_file.write("class {}Serializer(serializers.ModelSerializer):\n".format(relation["name"]))
        api_file.write("    class Meta:\n")
        api_file.write("        model = {}\n".format(relation["name"]))
        api_file.write("        fields = ['{}']\n".format("', '".join([f["name"] for f in relation["fields"]])))

        api_file.write("\n\n")

        api_file.write("class {}ViewSet(viewsets.ModelViewSet):\n".format(relation["name"]))
        api_file.write("    queryset = {}.objects.all()\n".format(relation["name"]))
        api_file.write("    serializer_class = {}Serializer\n\n".format(relation["name"]))
        api_file.write("    @action(detail=False)\n")
        api_file.write("    def categorical_counts(self, _request):\n")
        api_file.write("        counts = {}\n")
        api_file.write("        categorical_fields = ['{}']\n".format(
            "', '".join([f["name"] for f in relation["fields"] if "choices" in f])))
        api_file.write("        for row in {}.objects.values():\n".format(relation["name"]))
        api_file.write("            for f in categorical_fields:\n")
        api_file.write("                counts[f] = counts.get(f, {})\n")
        api_file.write("                counts[f][row[f]] = counts[f].get(row[f], 0) + 1\n")
        api_file.write("        return Response(counts)\n")

        api_file.write("\n\n")

        api_file.write("api_router.register(r'data/{}', {}ViewSet)\n".format(relation["name_lower"], relation["name"]))

        api_file.flush()

    api_file.seek(0)
    return api_file


TEMP_DIRECTORY = os.path.join(os.getcwd(), "tmp")


def print_usage():
    print("Usage: ptd-generate design.csv output_site_name")


def sanitize_and_check_site_name(site_name_raw: str) -> str:
    site_name_stripped = site_name_raw.strip()
    site_name = sanitize_python_identifier(site_name_stripped)

    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]+$", site_name):
        raise GenerationError("Error: Site name '{}' cannot be turned into a valid Python package name. \n"
                              "       Please choose a different name.".format(site_name_stripped))

    if site_name != site_name_stripped:
        print("Warning: Site name '{}' is not a valid Python package name; \n"
              "         using '{}' instead.\n".format(site_name_stripped, site_name))

    try:
        importlib.import_module(site_name)
        raise GenerationError("Error: Site name '{}' conflicts with a Python package name. \n"
                              "       Please choose a different name.".format(site_name))
    except ImportError:
        pass

    return site_name


def is_common_password(password: str, package_dir: str) -> bool:
    # Try to use password list created by Royce Williams and adapted for the Django project:
    # https://gist.github.com/roycewilliams/281ce539915a947a23db17137d91aeb7

    common_passwords = ["password", "123456", "12345678"]  # Fallbacks if file not present
    try:
        with gzip.open(os.path.join(package_dir, "common-passwords.txt.gz")) as f:
            common_passwords = {p.strip() for p in f.read().decode().splitlines()
                                if len(p.strip()) >= 8}  # Don't bother including too-short passwords
    except OSError:
        pass

    return password.lower().strip() in common_passwords


# TODO: TIMEZONES
# TODO: Multiple date formats
# TODO: More ways for custom validation
# TODO: More customization options


def main():
    print_license()

    if len(sys.argv) != 3:
        print_usage()
        exit(1)

    # TODO: EXPERIMENTAL: GIS MODE
    gis_mode = os.environ.get("PTD_GIS", "false").lower() == "true"
    spatialite_library_path = os.environ.get("SPATIALITE_LIBRARY_PATH", "")
    if gis_mode:
        print("Notice: Enabling experimental GIS mode...\n")
        if spatialite_library_path == "":
            exit_with_error("Error: Please set SPATIALITE_LIBRARY_PATH.")

    args = sys.argv[1:]

    package_dir = os.path.dirname(__file__)

    design_file = args[0]  # File name for design file input

    django_site_name = ""
    try:
        django_site_name = sanitize_and_check_site_name(args[1])
    except ValueError as e:
        exit_with_error(str(e))

    if not os.path.exists(TEMP_DIRECTORY):
        os.makedirs(TEMP_DIRECTORY)

    if os.name not in ("nt", "posix"):
        print("Unsupported platform.")
        exit(1)

    site_url = "localhost"

    a_buf = None
    m_buf = None
    api_buf = None

    # Process and validate design file, get contents of admin and models files
    try:
        print("Validating design file '{}'...".format(design_file))
        with open(os.path.join(os.getcwd(), design_file), "r") as df:
            try:
                relations = design_to_relation_fields(df, gis_mode)
                a_buf = create_admin(relations, django_site_name, gis_mode)
                m_buf = create_models(relations, gis_mode)
                api_buf = create_api(relations, django_site_name, gis_mode)
            except GenerationError as e:
                exit_with_error(str(e))
        print("done.\n")

        prod_build = input("Is this a production build? (y/n): ")
        if prod_build.lower() in ("y", "yes"):
            site_url = input("Please enter the production site URL, without 'www.' or 'http://': ")
            while "http:" in site_url or "https:" in site_url or "/www." in site_url:
                site_url = input("Please enter the production site URL, without 'www.' or 'http://': ")
        elif prod_build.lower() not in ("n", "no"):
            print("Invalid answer '{}', assuming 'n'...".format(prod_build))

        print()

        with a_buf, m_buf, api_buf:
            # Run site creation script
            # TODO: Make path more robust
            create_site_script = os.path.join(
                os.path.dirname(__file__),
                "os_scripts",
                "create_django_site.bat" if os.name == "nt" else "create_django_site.bash"
            )
            create_site_options = [create_site_script, package_dir, django_site_name, TEMP_DIRECTORY,
                                   "Dockerfile.gis.template" if gis_mode else "Dockerfile.template"]
            subprocess.run(create_site_options, check=True)

            # Write admin file contents to disk
            with open(os.path.join(TEMP_DIRECTORY, django_site_name, "core", "admin.py"), "w") as af:
                shutil.copyfileobj(a_buf, af)

            # Write model file contents to disk
            with open(os.path.join(TEMP_DIRECTORY, django_site_name, "core", "models.py"), "w") as mf:
                shutil.copyfileobj(m_buf, mf)

            # Write API specification file contents to disk
            with open(os.path.join(TEMP_DIRECTORY, django_site_name, "core", "api.py"), "w") as api_f:
                shutil.copyfileobj(api_buf, api_f)

        with open(os.path.join(TEMP_DIRECTORY, django_site_name, "snapshot_manager", "models.py"), "w") \
                as smf, open(os.path.join(TEMP_DIRECTORY, django_site_name, "snapshot_manager",
                                          "admin.py"), "w") as saf:
            smf.write(MODELS_FILE_HEADER.format(version=VERSION, models_path="django.db"))
            smf.write("\n")
            smf.write(SNAPSHOT_MODEL.format(site_name=django_site_name))
            saf.write(SNAPSHOT_ADMIN_FILE)

    except FileNotFoundError as e:
        print(str(e))
        exit_with_error("Error: Design file not found.")

    with open(os.path.join(TEMP_DIRECTORY, django_site_name, django_site_name, "settings.py"), "r+") as sf:
        old_contents = sf.read()

        sf.seek(0)

        new_contents = (
            old_contents.replace(INSTALLED_APPS_OLD, INSTALLED_APPS_NEW_GIS if gis_mode else INSTALLED_APPS_NEW)
                        .replace(DEBUG_OLD, DEBUG_NEW)
                        .replace(ALLOWED_HOSTS_OLD, ALLOWED_HOSTS_NEW.format(site_url))
                        .replace(STATIC_OLD, STATIC_NEW)
            + DISABLE_MAX_FIELDS
            + REST_FRAMEWORK_SETTINGS
        )

        if gis_mode:
            new_contents = new_contents.replace(DATABASE_ENGINE_NORMAL, DATABASE_ENGINE_GIS)
            new_contents += SPATIALITE_SETTINGS.format(spatialite_library_path)

        sf.write(new_contents)

        # TODO: May not need spatialite path in settings

        sf.truncate()

    with open(os.path.join(TEMP_DIRECTORY, django_site_name, django_site_name, "urls.py"), "r+") as uf:
        old_contents = uf.read()
        uf.seek(0)
        uf.write(old_contents.replace(URL_OLD, URL_NEW))
        uf.truncate()

    print("\n================ ADMINISTRATIVE SETUP ================")
    admin_username = input("Admin Account Username: ")
    while admin_username.strip() == "":
        print("Please enter a username.")
        admin_username = input("Admin Account Username: ")
    admin_email = input("Admin Account Email (Optional): ")
    admin_password = "1"
    admin_password_2 = "2"
    while admin_password != admin_password_2:
        admin_password = getpass.getpass("Admin Account Password: ")

        # TODO: Properly check password validity
        if len(admin_password.strip()) < 8:
            print("Error: Please enter a more secure password (8 or more characters).")
            admin_password = "1"
            admin_password_2 = "2"
            continue

        if is_common_password(admin_password, package_dir=package_dir):
            print("Error: Please enter in a less commonly-used password (8 or more characters).")
            admin_password = "1"
            admin_password_2 = "2"
            continue

        admin_password_2 = getpass.getpass("Admin Account Password Again: ")

        if admin_password != admin_password_2:
            print("Error: Passwords do not match. Please try again.")
    print("======================================================\n")

    try:
        # TODO: Make path more robust
        site_setup_script = os.path.join(
            package_dir,
            "os_scripts",
            "run_site_setup.bat" if os.name == "nt" else "run_site_setup.bash"
        )
        site_setup_options = [site_setup_script, os.path.dirname(__file__), django_site_name, TEMP_DIRECTORY,
                              admin_username, admin_email, admin_password, site_url]
        subprocess.run(site_setup_options, check=True)

    except subprocess.CalledProcessError:
        # Need to catch subprocess errors to prevent password from being shown onscreen.
        exit_with_error("Error: An error occurred while running the site setup script.\nTerminating...")

    shutil.make_archive(django_site_name, "zip", root_dir=os.path.join(os.getcwd(), "tmp"), base_dir=django_site_name)


if __name__ == "__main__":
    main()

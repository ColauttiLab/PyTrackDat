@echo off

rem Enter the temporary site construction directory
cd "%3"

rem Create and activate the virtual environment used for setup
virtualenv -p python3 tmp_env > nul 2> nul
if errorlevel 1 (
    virtualenv -p python tmp_env
)
call tmp_env\Scripts\activate.bat

rem Install the dependencies required for setup
pip install -r "%1\util_files\requirements_setup.txt"

rem Start the Django site
.\tmp_env\Scripts\django-admin startproject "%2"

rem Copy pre-built files to the site folder
copy /B "%1\util_files\requirements.txt" "%2\"
rem The GIS requirements file may go unused
copy /B "%1\util_files\requirements_gis.txt" "%2\"
copy /B "%1\util_files\%4" "%2\"
copy /B "%1\util_files\docker-compose.yml" "%2\"
copy /B "%1\util_files\nginx.conf" "%2\"
copy /B "%1\util_files\export_labels.R" "%2\"
copy /B "%1\util_files\install_dependencies.R" "%2\"

rem Enter the Django site directory
cd "%2"

rem Create the storage directory for snapshots
mkdir snapshots

rem Add site name to Dockerfile template
powershell -Command "(gc %4) -replace 'SITE_NAME', '%2' | Out-File Dockerfile"
del "%4"

rem Create the Django application for the models
python manage.py startapp core

rem Create the Django application for database snapshots
python manage.py startapp snapshot_manager

rem Copy pre-built application scripts to the application
xcopy "%1\app_includes" core /s /e
copy /B "%1\common.py" core

rem Deactivate the temporary setup virtual environment
deactivate

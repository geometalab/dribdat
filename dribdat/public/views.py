# -*- coding: utf-8 -*-
"""Public section, including homepage and signup."""
from flask import (Blueprint, request, render_template, flash, url_for,
                    redirect, session, current_app, jsonify)
from flask_login import login_required, current_user

from dribdat.user.models import User, Event, Project
from dribdat.public.forms import ProjectForm
from dribdat.database import db
from dribdat.aggregation import GetProjectData, ProjectActivity, IsProjectStarred, GetProjectTeam
from dribdat.extensions import cache
from dribdat.user import projectProgressList

blueprint = Blueprint('public', __name__, static_folder="../static")

def current_event():
    return Event.query.filter_by(is_current=True).first()

@blueprint.route("/")
def home():
    cur_event = current_event()
    if cur_event is not None:
        events = Event.query.filter(Event.id != cur_event.id)
    else:
        events = Event.query
    events = events.order_by(Event.id.desc()).all()
    return render_template("public/home.html",
        events=events, current_event=cur_event)

@blueprint.route("/about/")
def about():
    return render_template("public/about.html", current_event=current_event())

@blueprint.route("/dashboard/")
def dashboard():
    return render_template("public/dashboard.html", current_event=current_event())

@blueprint.route("/event/<int:event_id>")
def event(event_id):
    event = Event.query.filter_by(id=event_id).first_or_404()
    projects = Project.query.filter_by(event_id=event_id, is_hidden=False)
    if request.args.get('embed'):
        return render_template("public/embed.html", current_event=event, projects=projects)
    summaries = [ p.data for p in projects ]
    summaries.sort(key=lambda x: x['score'], reverse=True)
    return render_template("public/event.html",  current_event=event, projects=summaries)

@blueprint.route('/project/<int:project_id>')
def project(project_id):
    return project_action(project_id, None)

@blueprint.route('/project/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def project_edit(project_id):
    project = Project.query.filter_by(id=project_id).first_or_404()
    event = project.event
    starred = IsProjectStarred(project, current_user)
    allow_edit = starred or (not current_user.is_anonymous and current_user.is_admin)
    if not allow_edit:
        flash('You do not have access to edit this project.', 'warning')
        return project_action(project_id, None)
    form = ProjectForm(obj=project, next=request.args.get('next'))
    form.progress.choices = projectProgressList(event.has_started or event.has_finished)
    form.category_id.choices = [(c.id, c.name) for c in project.categories_for_event(event.id)]
    form.category_id.choices.insert(0, (-1, ''))
    if form.validate_on_submit():
        del form.id
        form.populate_obj(project)
        project.update()
        db.session.add(project)
        db.session.commit()
        cache.clear()
        flash('Project updated.', 'success')
        # TODO: return redirect(url_for('project', project_id=project.id))
        return project_action(project_id, 'update')
    return render_template('public/projectedit.html', current_event=event, project=project, form=form)

def project_action(project_id, of_type):
    project = Project.query.filter_by(id=project_id).first_or_404()
    event = project.event
    if of_type is not None:
        ProjectActivity(project, of_type, current_user)
    starred = IsProjectStarred(project, current_user)
    allow_edit = starred or (not current_user.is_anonymous and current_user.is_admin)
    project_stars = GetProjectTeam(project)
    return render_template('public/project.html', current_event=event, project=project,
        project_starred=starred, project_stars=project_stars, allow_edit=allow_edit)

@blueprint.route('/project/<int:project_id>/star', methods=['GET', 'POST'])
@login_required
def project_star(project_id):
    flash('Thanks for your support!', 'success')
    return project_action(project_id, 'star')

@blueprint.route('/project/<int:project_id>/unstar', methods=['GET', 'POST'])
@login_required
def project_unstar(project_id):
    flash('Project un-starred', 'success')
    return project_action(project_id, 'unstar')

@blueprint.route('/event/<int:event_id>/project/new', methods=['GET', 'POST'])
def project_new(event_id):
    form = None
    event = Event.query.filter_by(id=event_id).first_or_404()
    if current_user and current_user.is_authenticated:
        project = Project()
        project.user_id = current_user.id
        form = ProjectForm(obj=project, next=request.args.get('next'))
        form.progress.choices = projectProgressList(event.has_started)
        form.category_id.choices = [(c.id, c.name) for c in project.categories_for_event(event.id)]
        form.category_id.choices.insert(0, (-1, ''))
        if form.validate_on_submit():
            del form.id
            form.populate_obj(project)
            project.event = event
            project.update()
            db.session.add(project)
            db.session.commit()
            flash('Project added.', 'success')
            project_action(project.id, 'create')
            cache.clear()
            return project_action(project.id, 'star')
        del form.logo_icon
        del form.logo_color
    return render_template('public/projectnew.html', current_event=event, form=form)

@blueprint.route('/project/<int:project_id>/autoupdate')
@login_required
def project_autoupdate(project_id):
    project = Project.query.filter_by(id=project_id).first_or_404()
    starred = IsProjectStarred(project, current_user)
    allow_edit = starred or (not current_user.is_anonymous and current_user.is_admin)
    if not allow_edit or project.is_hidden or not project.is_autoupdate:
        flash('You may not sync this project.', 'warning')
        return project_action(project_id, None)
    data = GetProjectData(project.autotext_url)
    if not 'name' in data:
        flash("Project could not be synced: check the autoupdate link.", 'warning')
        return project_action(project_id, None)
    if 'name' in data and data['name']:
        project.name = data['name']
    if 'summary' in data and data['summary']:
        project.summary = data['summary']
    if 'description' in data and data['description']:
        project.longtext = data['description']
    if 'homepage_url' in data and data['homepage_url']:
        project.webpage_url = data['homepage_url']
    if 'contact_url' in data and data['contact_url']:
        project.contact_url = data['contact_url']
    if 'source_url' in data and data['source_url']:
        project.source_url = data['source_url']
    if 'image_url' in data and data['image_url']:
        project.image_url = data['image_url']
    project.update()
    db.session.add(project)
    db.session.commit()
    flash("Project data synced.", 'success')
    return project_action(project.id, 'update')

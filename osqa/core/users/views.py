import time, datetime, calendar, random

from django.shortcuts import render_to_response, get_object_or_404
from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseForbidden, Http404
from django.template import RequestContext
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext as _
from django.contrib.auth.decorators import login_required
from django.utils.html import *
from django.core.mail import mail_admins
from django.utils import simplejson

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from osqa.core.shared.forms import get_next_url
from osqa.core.meta.views import tags
from osqa.models import *
from osqa.utils.html import sanitize_html
from auth import *
import auth
from forms import *
from user import *

USERS_PAGE_SIZE = 35

question_type = ContentType.objects.get_for_model(Question)
answer_type = ContentType.objects.get_for_model(Answer)
comment_type = ContentType.objects.get_for_model(Comment)
question_revision_type = ContentType.objects.get_for_model(QuestionRevision)
answer_revision_type = ContentType.objects.get_for_model(AnswerRevision)
repute_type = ContentType.objects.get_for_model(Repute)
question_type_id = question_type.id
answer_type_id = answer_type.id
comment_type_id = comment_type.id
question_revision_type_id = question_revision_type.id
answer_revision_type_id = answer_revision_type.id
repute_type_id = repute_type.id

def users(request):
    is_paginated = True
    sortby = request.GET.get('sort', 'reputation')
    suser = request.REQUEST.get('q',  "")
    try:
        page = int(request.GET.get('page', '1'))
    except ValueError:
        page = 1

    if suser == "":
        if sortby == "newest":
            objects_list = Paginator(User.objects.all().order_by('-date_joined'), USERS_PAGE_SIZE)
        elif sortby == "last":
            objects_list = Paginator(User.objects.all().order_by('date_joined'), USERS_PAGE_SIZE)
        elif sortby == "user":
            objects_list = Paginator(User.objects.all().order_by('username'), USERS_PAGE_SIZE)
        # default
        else:
            objects_list = Paginator(User.objects.all().order_by('-reputation'), USERS_PAGE_SIZE)
        base_url = reverse('users') + '?sort=%s&' % sortby
    else:
        sortby = "reputation"
        objects_list = Paginator(User.objects.extra(where=['username like %s'], params=['%' + suser + '%']).order_by('-reputation'), USERS_PAGE_SIZE)
        base_url = reverse('users') + '?name=%s&sort=%s&' % (suser, sortby)

    try:
        users = objects_list.page(page)
    except (EmptyPage, InvalidPage):
        users = objects_list.page(objects_list.num_pages)

    return render_to_response('users.html', {
                                "users" : users,
                                "suser" : suser,
                                "keywords" : suser,
                                "tab_id" : sortby,
                                "context" : {
                                    'is_paginated' : is_paginated,
                                    'pages': objects_list.num_pages,
                                    'page': page,
                                    'has_previous': users.has_previous(),
                                    'has_next': users.has_next(),
                                    'previous': users.previous_page_number(),
                                    'next': users.next_page_number(),
                                    'base_url' : base_url
                                }

                                }, context_instance=RequestContext(request))

def user(request, id):
    sort = request.GET.get('sort', 'stats')
    user_view = dict((v.id, v) for v in USER_TEMPLATE_VIEWS).get(sort, USER_TEMPLATE_VIEWS[0])
    import views
    func = getattr(views, user_view.view_name)
    return func(request, id, user_view)

def user_stats(request, user_id, user_view):
    user = get_object_or_404(User, id=user_id)
    questions = Question.objects.extra(
        select={
            'vote_count' : 'question.score',
            'favorited_myself' : 'SELECT count(*) FROM favorite_question f WHERE f.user_id = %s AND f.question_id = question.id',
            'la_user_id' : 'auth_user.id',
            'la_username' : 'auth_user.username',
            'la_user_gold' : 'auth_user.gold',
            'la_user_silver' : 'auth_user.silver',
            'la_user_bronze' : 'auth_user.bronze',
            'la_user_reputation' : 'auth_user.reputation'
            },
        select_params=[user_id],
        tables=['question', 'auth_user'],
        where=['question.deleted=False AND question.author_id=%s AND question.last_activity_by_id = auth_user.id'],
        params=[user_id],
        order_by=['-vote_count', '-last_activity_at']
    ).values('vote_count',
             'favorited_myself',
             'id',
             'title',
             'author_id',
             'added_at',
             'answer_accepted',
             'answer_count',
             'comment_count',
             'view_count',
             'favourite_count',
             'summary',
             'tagnames',
             'vote_up_count',
             'vote_down_count',
             'last_activity_at',
             'la_user_id',
             'la_username',
             'la_user_gold',
             'la_user_silver',
             'la_user_bronze',
             'la_user_reputation')[:100]

    answered_questions = Question.objects.extra(
        select={
            'vote_up_count' : 'answer.vote_up_count',
            'vote_down_count' : 'answer.vote_down_count',
            'answer_id' : 'answer.id',
            'accepted' : 'answer.accepted',
            'vote_count' : 'answer.score',
            'comment_count' : 'answer.comment_count'
            },
        tables=['question', 'answer'],
        where=['answer.deleted=False AND question.deleted=False AND answer.author_id=%s AND answer.question_id=question.id'],
        params=[user_id],
        order_by=['-vote_count', '-answer_id'],
        select_params=[user_id]
    ).distinct().values('comment_count',
                        'id',
                        'answer_id',
                        'title',
                        'author_id',
                        'accepted',
                        'vote_count',
                        'answer_count',
                        'vote_up_count',
                        'vote_down_count')[:100]

    up_votes = Vote.objects.get_up_vote_count_from_user(user)
    down_votes = Vote.objects.get_down_vote_count_from_user(user)
    votes_today = Vote.objects.get_votes_count_today_from_user(user)
    votes_total = VOTE_RULES['scope_votes_per_user_per_day']

    question_id_set = set(map(lambda v: v['id'], list(questions))) \
                        | set(map(lambda v: v['id'], list(answered_questions)))

    user_tags = Tag.objects.filter(questions__id__in = question_id_set)
    try:
        from django.db.models import Count
        awards = Award.objects.extra(
                                        select={'id': 'badge.id',
                                                'name':'badge.name',
                                                'description': 'badge.description',
                                                'type': 'badge.type'},
                                        tables=['award', 'badge'],
                                        order_by=['-awarded_at'],
                                        where=['user_id=%s AND badge_id=badge.id'],
                                        params=[user.id]
                                    ).values('id', 'name', 'description', 'type')
        total_awards = awards.count()
        awards = awards.annotate(count = Count('badge__id'))
        user_tags = user_tags.annotate(user_tag_usage_count=Count('name'))

    except ImportError:
        awards = Award.objects.extra(
                                        select={'id': 'badge.id',
                                                'count': 'count(badge_id)',
                                                'name':'badge.name',
                                                'description': 'badge.description',
                                                'type': 'badge.type'},
                                        tables=['award', 'badge'],
                                        order_by=['-awarded_at'],
                                        where=['user_id=%s AND badge_id=badge.id'],
                                        params=[user.id]
                                    ).values('id', 'count', 'name', 'description', 'type')
        total_awards = awards.count()
        awards.query.group_by = ['badge_id']

        user_tags = user_tags.extra(
            select={'user_tag_usage_count': 'COUNT(1)',},
            order_by=['-user_tag_usage_count'],
        )
        user_tags.query.group_by = ['name']

    if auth.can_moderate_users(request.user):
        moderate_user_form = ModerateUserForm(instance=user)
    else:
        moderate_user_form = None

    return render_to_response(user_view.template_file,{
                                'moderate_user_form': moderate_user_form,
                                "tab_name" : user_view.id,
                                "tab_description" : user_view.tab_description,
                                "page_title" : user_view.page_title,
                                "view_user" : user,
                                "questions" : questions,
                                "answered_questions" : answered_questions,
                                "up_votes" : up_votes,
                                "down_votes" : down_votes,
                                "total_votes": up_votes + down_votes,
                                "votes_today_left": votes_total-votes_today,
                                "votes_total_per_day": votes_total,
                                "user_tags" : user_tags[:50],
                                "tags" : tags,
                                "awards": awards,
                                "total_awards" : total_awards,
                            }, context_instance=RequestContext(request))

def user_recent(request, user_id, user_view):
    user = get_object_or_404(User, id=user_id)
    def get_type_name(type_id):
        for item in TYPE_ACTIVITY:
            if type_id in item:
                return item[1]

    class Event:
        def __init__(self, time, type, title, summary, answer_id, question_id):
            self.time = time
            self.type = get_type_name(type)
            self.type_id = type
            self.title = title
            self.summary = summary
            slug_title = slugify(title)
            self.title_link = reverse('question', kwargs={'id':question_id}) + u'%s' % slug_title
            if int(answer_id) > 0:
                self.title_link += '#%s' % answer_id

    class AwardEvent:
        def __init__(self, time, type, id):
            self.time = time
            self.type = get_type_name(type)
            self.type_id = type
            self.badge = get_object_or_404(Badge, id=id)

    activities = []
    # ask questions
    questions = Activity.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'active_at' : 'activity.active_at',
            'activity_type' : 'activity.activity_type'
            },
        tables=['activity', 'question'],
        where=['activity.content_type_id = %s AND activity.object_id = ' +
            'question.id AND question.deleted=False AND activity.user_id = %s AND activity.activity_type = %s'],
        params=[question_type_id, user_id, TYPE_ACTIVITY_ASK_QUESTION],
        order_by=['-activity.active_at']
    ).values(
            'title',
            'question_id',
            'active_at',
            'activity_type'
            )
    if len(questions) > 0:
        questions = [(Event(q['active_at'], q['activity_type'], q['title'], '', '0', \
                      q['question_id'])) for q in questions]
        activities.extend(questions)

    # answers
    answers = Activity.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 'answer.id',
            'active_at' : 'activity.active_at',
            'activity_type' : 'activity.activity_type'
            },
        tables=['activity', 'answer', 'question'],
        where=['activity.content_type_id = %s AND activity.object_id = answer.id AND ' +
            'answer.question_id=question.id AND answer.deleted=False AND activity.user_id=%s AND '+
            'activity.activity_type=%s AND question.deleted=False'],
        params=[answer_type_id, user_id, TYPE_ACTIVITY_ANSWER],
        order_by=['-activity.active_at']
    ).values(
            'title',
            'question_id',
            'answer_id',
            'active_at',
            'activity_type'
            )
    if len(answers) > 0:
        answers = [(Event(q['active_at'], q['activity_type'], q['title'], '', q['answer_id'], \
                    q['question_id'])) for q in answers]
        activities.extend(answers)

    # question comments
    comments = Activity.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'comment.object_id',
            'added_at' : 'comment.added_at',
            'activity_type' : 'activity.activity_type'
            },
        tables=['activity', 'question', 'comment'],

        where=['activity.content_type_id = %s AND activity.object_id = comment.id AND '+
            'activity.user_id = comment.user_id AND comment.object_id=question.id AND '+
            'comment.content_type_id=%s AND activity.user_id = %s AND activity.activity_type=%s AND ' +
            'question.deleted=False'],
        params=[comment_type_id, question_type_id, user_id, TYPE_ACTIVITY_COMMENT_QUESTION],
        order_by=['-comment.added_at']
    ).values(
            'title',
            'question_id',
            'added_at',
            'activity_type'
            )

    if len(comments) > 0:
        comments = [(Event(q['added_at'], q['activity_type'], q['title'], '', '0', \
                     q['question_id'])) for q in comments]
        activities.extend(comments)

    # answer comments
    comments = Activity.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 'answer.id',
            'added_at' : 'comment.added_at',
            'activity_type' : 'activity.activity_type'
            },
        tables=['activity', 'question', 'answer', 'comment'],

        where=['activity.content_type_id = %s AND activity.object_id = comment.id AND '+
            'activity.user_id = comment.user_id AND comment.object_id=answer.id AND '+
            'comment.content_type_id=%s AND question.id = answer.question_id AND '+
            'activity.user_id = %s AND activity.activity_type=%s AND '+
            'answer.deleted=False AND question.deleted=False'],
        params=[comment_type_id, answer_type_id, user_id, TYPE_ACTIVITY_COMMENT_ANSWER],
        order_by=['-comment.added_at']
    ).values(
            'title',
            'question_id',
            'answer_id',
            'added_at',
            'activity_type'
            )

    if len(comments) > 0:
        comments = [(Event(q['added_at'], q['activity_type'], q['title'], '', q['answer_id'], \
                     q['question_id'])) for q in comments]
        activities.extend(comments)

    # question revisions
    revisions = Activity.objects.extra(
        select={
            'title' : 'question_revision.title',
            'question_id' : 'question_revision.question_id',
            'added_at' : 'activity.active_at',
            'activity_type' : 'activity.activity_type',
            'summary' : 'question_revision.summary'
            },
        tables=['activity', 'question_revision', 'question'],
        where=['activity.content_type_id = %s AND activity.object_id = question_revision.id AND '+
            'question_revision.id=question.id AND question.deleted=False AND '+
            'activity.user_id = question_revision.author_id AND activity.user_id = %s AND '+
            'activity.activity_type=%s'],
        params=[question_revision_type_id, user_id, TYPE_ACTIVITY_UPDATE_QUESTION],
        order_by=['-activity.active_at']
    ).values(
            'title',
            'question_id',
            'added_at',
            'activity_type',
            'summary'
            )

    if len(revisions) > 0:
        revisions = [(Event(q['added_at'], q['activity_type'], q['title'], q['summary'], '0', \
                      q['question_id'])) for q in revisions]
        activities.extend(revisions)

    # answer revisions
    revisions = Activity.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 'answer.id',
            'added_at' : 'activity.active_at',
            'activity_type' : 'activity.activity_type',
            'summary' : 'answer_revision.summary'
            },
        tables=['activity', 'answer_revision', 'question', 'answer'],

        where=['activity.content_type_id = %s AND activity.object_id = answer_revision.id AND '+
            'activity.user_id = answer_revision.author_id AND activity.user_id = %s AND '+
            'answer_revision.answer_id=answer.id AND answer.question_id = question.id AND '+
            'question.deleted=False AND answer.deleted=False AND '+
            'activity.activity_type=%s'],
        params=[answer_revision_type_id, user_id, TYPE_ACTIVITY_UPDATE_ANSWER],
        order_by=['-activity.active_at']
    ).values(
            'title',
            'question_id',
            'added_at',
            'answer_id',
            'activity_type',
            'summary'
            )

    if len(revisions) > 0:
        revisions = [(Event(q['added_at'], q['activity_type'], q['title'], q['summary'], \
                      q['answer_id'], q['question_id'])) for q in revisions]
        activities.extend(revisions)

    # accepted answers
    accept_answers = Activity.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'added_at' : 'activity.active_at',
            'activity_type' : 'activity.activity_type',
            },
        tables=['activity', 'answer', 'question'],
        where=['activity.content_type_id = %s AND activity.object_id = answer.id AND '+
            'activity.user_id = question.author_id AND activity.user_id = %s AND '+
            'answer.deleted=False AND question.deleted=False AND '+
            'answer.question_id=question.id AND activity.activity_type=%s'],
        params=[answer_type_id, user_id, TYPE_ACTIVITY_MARK_ANSWER],
        order_by=['-activity.active_at']
    ).values(
            'title',
            'question_id',
            'added_at',
            'activity_type',
            )
    if len(accept_answers) > 0:
        accept_answers = [(Event(q['added_at'], q['activity_type'], q['title'], '', '0', \
            q['question_id'])) for q in accept_answers]
        activities.extend(accept_answers)
    #award history
    awards = Activity.objects.extra(
        select={
            'badge_id' : 'badge.id',
            'awarded_at': 'award.awarded_at',
            'activity_type' : 'activity.activity_type'
            },
        tables=['activity', 'award', 'badge'],
        where=['activity.user_id = award.user_id AND activity.user_id = %s AND '+
            'award.badge_id=badge.id AND activity.object_id=award.id AND activity.activity_type=%s'],
        params=[user_id, TYPE_ACTIVITY_PRIZE],
        order_by=['-activity.active_at']
    ).values(
            'badge_id',
            'awarded_at',
            'activity_type'
            )
    if len(awards) > 0:
        awards = [(AwardEvent(q['awarded_at'], q['activity_type'], q['badge_id'])) for q in awards]
        activities.extend(awards)

    activities.sort(lambda x,y: cmp(y.time, x.time))

    return render_to_response(user_view.template_file,{
                                    "tab_name" : user_view.id,
                                    "tab_description" : user_view.tab_description,
                                    "page_title" : user_view.page_title,
                                    "view_user" : user,
                                    "activities" : activities[:user_view.data_size]
                                }, context_instance=RequestContext(request))

def user_responses(request, user_id, user_view):
    """
    We list answers for question, comments, and answer accepted by others for this user.
    """
    class Response:
        def __init__(self, type, title, question_id, answer_id, time, username, user_id, content):
            self.type = type
            self.title = title
            self.titlelink = reverse('question', args=[question_id]) + u'%s#%s' % (slugify(title), answer_id)
            self.time = time
            self.userlink = reverse('users') + u'%s/%s/' % (user_id, username)
            self.username = username
            self.content = u'%s ...' % strip_tags(content)[:300]

        def __unicode__(self):
            return u'%s %s' % (self.type, self.titlelink)

    user = get_object_or_404(User, id=user_id)
    responses = []
    answers = Answer.objects.extra(
                                    select={
                                        'title' : 'question.title',
                                        'question_id' : 'question.id',
                                        'answer_id' : 'answer.id',
                                        'added_at' : 'answer.added_at',
                                        'html' : 'answer.html',
                                        'username' : 'auth_user.username',
                                        'user_id' : 'auth_user.id'
                                        },
                                    select_params=[user_id],
                                    tables=['answer', 'question', 'auth_user'],
                                    where=['answer.question_id = question.id AND answer.deleted=False AND question.deleted=False AND '+
                                        'question.author_id = %s AND answer.author_id <> %s AND answer.author_id=auth_user.id'],
                                    params=[user_id, user_id],
                                    order_by=['-answer.id']
                                ).values(
                                        'title',
                                        'question_id',
                                        'answer_id',
                                        'added_at',
                                        'html',
                                        'username',
                                        'user_id'
                                        )
    if len(answers) > 0:
        answers = [(Response(TYPE_RESPONSE['QUESTION_ANSWERED'], a['title'], a['question_id'],
        a['answer_id'], a['added_at'], a['username'], a['user_id'], a['html'])) for a in answers]
        responses.extend(answers)


    # question comments
    comments = Comment.objects.extra(
                                select={
                                    'title' : 'question.title',
                                    'question_id' : 'comment.object_id',
                                    'added_at' : 'comment.added_at',
                                    'comment' : 'comment.comment',
                                    'username' : 'auth_user.username',
                                    'user_id' : 'auth_user.id'
                                    },
                                tables=['question', 'auth_user', 'comment'],
                                where=['question.deleted=False AND question.author_id = %s AND comment.object_id=question.id AND '+
                                    'comment.content_type_id=%s AND comment.user_id <> %s AND comment.user_id = auth_user.id'],
                                params=[user_id, question_type_id, user_id],
                                order_by=['-comment.added_at']
                            ).values(
                                    'title',
                                    'question_id',
                                    'added_at',
                                    'comment',
                                    'username',
                                    'user_id'
                                    )

    if len(comments) > 0:
        comments = [(Response(TYPE_RESPONSE['QUESTION_COMMENTED'], c['title'], c['question_id'],
            '', c['added_at'], c['username'], c['user_id'], c['comment'])) for c in comments]
        responses.extend(comments)

    # answer comments
    comments = Comment.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 'answer.id',
            'added_at' : 'comment.added_at',
            'comment' : 'comment.comment',
            'username' : 'auth_user.username',
            'user_id' : 'auth_user.id'
            },
        tables=['answer', 'auth_user', 'comment', 'question'],
        where=['answer.deleted=False AND answer.author_id = %s AND comment.object_id=answer.id AND '+
            'comment.content_type_id=%s AND comment.user_id <> %s AND comment.user_id = auth_user.id '+
            'AND question.id = answer.question_id'],
        params=[user_id, answer_type_id, user_id],
        order_by=['-comment.added_at']
    ).values(
            'title',
            'question_id',
            'answer_id',
            'added_at',
            'comment',
            'username',
            'user_id'
            )

    if len(comments) > 0:
        comments = [(Response(TYPE_RESPONSE['ANSWER_COMMENTED'], c['title'], c['question_id'],
        c['answer_id'], c['added_at'], c['username'], c['user_id'], c['comment'])) for c in comments]
        responses.extend(comments)

    # answer has been accepted
    answers = Answer.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 'answer.id',
            'added_at' : 'answer.accepted_at',
            'html' : 'answer.html',
            'username' : 'auth_user.username',
            'user_id' : 'auth_user.id'
            },
        select_params=[user_id],
        tables=['answer', 'question', 'auth_user'],
        where=['answer.question_id = question.id AND answer.deleted=False AND question.deleted=False AND '+
            'answer.author_id = %s AND answer.accepted=True AND question.author_id=auth_user.id'],
        params=[user_id],
        order_by=['-answer.id']
    ).values(
            'title',
            'question_id',
            'answer_id',
            'added_at',
            'html',
            'username',
            'user_id'
            )
    if len(answers) > 0:
        answers = [(Response(TYPE_RESPONSE['ANSWER_ACCEPTED'], a['title'], a['question_id'],
            a['answer_id'], a['added_at'], a['username'], a['user_id'], a['html'])) for a in answers]
        responses.extend(answers)

    # sort posts by time
    responses.sort(lambda x,y: cmp(y.time, x.time))

    return render_to_response(user_view.template_file,{
        "tab_name" : user_view.id,
        "tab_description" : user_view.tab_description,
        "page_title" : user_view.page_title,
        "view_user" : user,
        "responses" : responses[:user_view.data_size],

    }, context_instance=RequestContext(request))

def user_votes(request, user_id, user_view):
    user = get_object_or_404(User, id=user_id)
    if not can_view_user_votes(request.user, user):
        raise Http404
    votes = []
    question_votes = Vote.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 0,
            'voted_at' : 'vote.voted_at',
            'vote' : 'vote',
            },
        select_params=[user_id],
        tables=['vote', 'question', 'auth_user'],
        where=['vote.content_type_id = %s AND vote.user_id = %s AND vote.object_id = question.id '+
            'AND vote.user_id=auth_user.id'],
        params=[question_type_id, user_id],
        order_by=['-vote.id']
    ).values(
            'title',
            'question_id',
            'answer_id',
            'voted_at',
            'vote',
            )
    if(len(question_votes) > 0):
        votes.extend(question_votes)

    answer_votes = Vote.objects.extra(
        select={
            'title' : 'question.title',
            'question_id' : 'question.id',
            'answer_id' : 'answer.id',
            'voted_at' : 'vote.voted_at',
            'vote' : 'vote',
            },
        select_params=[user_id],
        tables=['vote', 'answer', 'question', 'auth_user'],
        where=['vote.content_type_id = %s AND vote.user_id = %s AND vote.object_id = answer.id '+
            'AND answer.question_id = question.id AND vote.user_id=auth_user.id'],
        params=[answer_type_id, user_id],
        order_by=['-vote.id']
    ).values(
            'title',
            'question_id',
            'answer_id',
            'voted_at',
            'vote',
            )
    if(len(answer_votes) > 0):
        votes.extend(answer_votes)
    votes.sort(lambda x,y: cmp(y['voted_at'], x['voted_at']))
    return render_to_response(user_view.template_file,{
        "tab_name" : user_view.id,
        "tab_description" : user_view.tab_description,
        "page_title" : user_view.page_title,
        "view_user" : user,
        "votes" : votes[:user_view.data_size]

    }, context_instance=RequestContext(request))

def user_reputation(request, user_id, user_view):
    user = get_object_or_404(User, id=user_id)
    try:
        from django.db.models import Sum
        reputation = Repute.objects.extra(
                                          select={'question_id':'question_id',
                                          'title': 'question.title'},
                                          tables=['repute', 'question'],
                                          order_by=['-reputed_at'],
                                          where=['user_id=%s AND question_id=question.id'],
                                          params=[user.id]
                                          ).values('question_id', 'title', 'reputed_at', 'reputation')
        reputation = reputation.annotate(positive=Sum("positive"), negative=Sum("negative"))
    except ImportError:
        reputation = Repute.objects.extra(
                                          select={'positive':'sum(positive)', 'negative':'sum(negative)', 'question_id':'question_id',
                                          'title': 'question.title'},
                                          tables=['repute', 'question'],
                                          order_by=['-reputed_at'],
                                          where=['user_id=%s AND question_id=question.id'],
                                          params=[user.id]
                                          ).values('positive', 'negative', 'question_id', 'title', 'reputed_at', 'reputation')
        reputation.query.group_by = ['question_id']

    rep_list = []
    for rep in Repute.objects.filter(user=user).order_by('reputed_at'):
        dic = '[%s,%s]' % (calendar.timegm(rep.reputed_at.timetuple()) * 1000, rep.reputation)
        rep_list.append(dic)
    reps = ','.join(rep_list)
    reps = '[%s]' % reps

    return render_to_response(user_view.template_file, {
                              "tab_name": user_view.id,
                              "tab_description": user_view.tab_description,
                              "page_title": user_view.page_title,
                              "view_user": user,
                              "reputation": reputation,
                              "reps": reps
                              }, context_instance=RequestContext(request))

def user_favorites(request, user_id, user_view):
    user = get_object_or_404(User, id=user_id)
    questions = Question.objects.extra(
        select={
            'vote_count' : 'question.vote_up_count + question.vote_down_count',
            'favorited_myself' : 'SELECT count(*) FROM favorite_question f WHERE f.user_id = %s '+
                'AND f.question_id = question.id',
            'la_user_id' : 'auth_user.id',
            'la_username' : 'auth_user.username',
            'la_user_gold' : 'auth_user.gold',
            'la_user_silver' : 'auth_user.silver',
            'la_user_bronze' : 'auth_user.bronze',
            'la_user_reputation' : 'auth_user.reputation'
            },
        select_params=[user_id],
        tables=['question', 'auth_user', 'favorite_question'],
        where=['question.deleted=True AND question.last_activity_by_id = auth_user.id '+
            'AND favorite_question.question_id = question.id AND favorite_question.user_id = %s'],
        params=[user_id],
        order_by=['-vote_count', '-question.id']
    ).values('vote_count',
             'favorited_myself',
             'id',
             'title',
             'author_id',
             'added_at',
             'answer_accepted',
             'answer_count',
             'comment_count',
             'view_count',
             'favourite_count',
             'summary',
             'tagnames',
             'vote_up_count',
             'vote_down_count',
             'last_activity_at',
             'la_user_id',
             'la_username',
             'la_user_gold',
             'la_user_silver',
             'la_user_bronze',
             'la_user_reputation')
    return render_to_response(user_view.template_file,{
        "tab_name" : user_view.id,
        "tab_description" : user_view.tab_description,
        "page_title" : user_view.page_title,
        "questions" : questions[:user_view.data_size],
        "view_user" : user
    }, context_instance=RequestContext(request))

def user_email_subscriptions(request, user_id, user_view):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        email_feeds_form = EditUserEmailFeedsForm(request.POST)
        tag_filter_form = TagFilterSelectionForm(request.POST, instance=user)
        if email_feeds_form.is_valid() and tag_filter_form.is_valid():

            action_status = None
            tag_filter_saved = tag_filter_form.save()
            if tag_filter_saved:
                action_status = _('changes saved')
            if 'save' in request.POST:
                feeds_saved = email_feeds_form.save(user)
                if feeds_saved:
                    action_status = _('changes saved')
            elif 'stop_email' in request.POST:
                email_stopped = email_feeds_form.reset().save(user)
                initial_values = EditUserEmailFeedsForm.NO_EMAIL_INITIAL
                email_feeds_form = EditUserEmailFeedsForm(initial=initial_values)
                if email_stopped:
                    action_status = _('email updates canceled')
    else:
        email_feeds_form = EditUserEmailFeedsForm()
        email_feeds_form.set_initial_values(user)
        tag_filter_form = TagFilterSelectionForm(instance=user)
        action_status = None
    return render_to_response(user_view.template_file,{
        'tab_name':user_view.id,
        'tab_description':user_view.tab_description,
        'page_title':user_view.page_title,
        'view_user':user,
        'email_feeds_form':email_feeds_form,
        'tag_filter_selection_form':tag_filter_form,
        'action_status':action_status,
    }, context_instance=RequestContext(request))

def feedback(request):
    data = {}
    form = None
    if request.method == "POST":
        form = FeedbackForm(request.POST)
        if form.is_valid():
            if not request.user.is_authenticated:
                data['email'] = form.cleaned_data.get('email',None)
            data['message'] = form.cleaned_data['message']
            data['name'] = form.cleaned_data.get('name',None)
            message = render_to_response('feedback_email.txt',data,context_instance=RequestContext(request))
            mail_admins(_('Q&A forum feedback'), message)
            msg = _('Thanks for the feedback!')
            request.user.message_set.create(message=msg)
            return HttpResponseRedirect(get_next_url(request))
    else:
        form = FeedbackForm(initial={'next':get_next_url(request)})

    data['form'] = form
    return render_to_response('feedback.html', data, context_instance=RequestContext(request))
feedback.CANCEL_MESSAGE=_('We look forward to hearing your feedback! Please, give it next time :)')

def logout(request):
    return render_to_response('logout.html', {
        'next' : get_next_url(request),
    }, context_instance=RequestContext(request))

@login_required
def edit_user(request, id):
    user = get_object_or_404(User, id=id)
    if request.user != user:
        raise Http404
    if request.method == "POST":
        form = EditUserForm(user, request.POST)
        if form.is_valid():
            new_email = sanitize_html(form.cleaned_data['email'])

            from django_authopenid.views import set_new_email
            set_new_email(user, new_email)

            #user.username = sanitize_html(form.cleaned_data['username'])
            user.real_name = sanitize_html(form.cleaned_data['realname'])
            user.website = sanitize_html(form.cleaned_data['website'])
            user.location = sanitize_html(form.cleaned_data['city'])
            user.date_of_birth = sanitize_html(form.cleaned_data['birthday'])
            if len(user.date_of_birth) == 0:
                user.date_of_birth = '1900-01-01'
            user.about = sanitize_html(form.cleaned_data['about'])

            user.save()
            # send user updated singal if full fields have been updated
            if user.email and user.real_name and user.website and user.location and \
                user.date_of_birth and user.about:
                user_updated.send(sender=user.__class__, instance=user, updated_by=user)
            return HttpResponseRedirect(user.get_profile_url())
    else:
        form = EditUserForm(user)
    return render_to_response('user_edit.html', {
                                                'form' : form,
                                                'gravatar_faq_url' : reverse('faq') + '#gravatar',
                                    }, context_instance=RequestContext(request))

@login_required
def moderate_user(request, id):
    """ajax handler of user moderation
    """
    if not auth.can_moderate_users(request.user) or request.method != 'POST':
        raise Http404
    if not request.is_ajax():
        return HttpResponseForbidden(mimetype="application/json")

    user = get_object_or_404(User, id=id)
    form = ModerateUserForm(request.POST, instance=user)

    if form.is_valid():
        form.save()
        logging.debug('data saved')
        response = HttpResponse(simplejson.dumps(''), mimetype="application/json")
    else:
        response = HttpResponseForbidden(mimetype="application/json")
    return response
    
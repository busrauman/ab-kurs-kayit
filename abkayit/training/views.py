# -*- coding: utf-8 -*-

import json
import logging
import itertools
from datetime import datetime

from django.shortcuts import render, render_to_response, RequestContext, redirect
from django.http.response import HttpResponseRedirect, HttpResponse
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse_lazy
from django.utils.translation import ugettext_lazy as _
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.utils import timezone
from django.db.models import Q

from abkayit.backend import prepare_template_data
from abkayit.adaptor import send_email
from abkayit.models import Site, Menu, ApprovalDate
from abkayit.decorators import active_required
from abkayit.settings import PREFERENCE_LIMIT, ADDITION_PREFERENCE_LIMIT, EMAIL_FROM_ADDRESS, TRAINESS_SCORE

from userprofile.models import UserProfile
from userprofile.forms import InstProfileForm,CreateInstForm
from userprofile.userprofileops import UserProfileOPS

from training.models import Course, TrainessCourseRecord
from training.forms import CreateCourseForm

log=logging.getLogger(__name__)

DATETIME_FORMAT="%d/%m/%Y %H:%M"

@login_required(login_url='/')
@user_passes_test(active_required, login_url=reverse_lazy("active_resend"))
def submitandregister(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    data=prepare_template_data(request)
    userops=UserProfileOPS()
    # TODO:site ve pages'e bi care bulmak lazim
    site=Site.objects.get(is_active=True)
    pages=Menu.objects.filter(site=site.pk).order_by('order')
    note="Kurs onerisi olustur:"
    try:
        curuserprof=UserProfile.objects.get(user=request.user)
    except:
        log.info("%s kullanici profili bulunamadi" % (request.user),extra=d)
    curinstprofform=InstProfileForm(prefix="cur")
    forms={}
    for x in xrange(4):
        forms[x]=[CreateInstForm(prefix=str(x)+"inst"),InstProfileForm(prefix=str(x)+"instprof")]
    form=CreateCourseForm()
    if "submit" in request.POST:
        allf=[]
        forms={}
        for x in xrange(4):
            if str(x)+"inst-email" in request.POST:
                forms[x]=[CreateInstForm(request.POST,prefix=str(x)+"inst"),InstProfileForm(request.POST,prefix=str(x)+"instprof")]
                allf.append(forms[x][0].is_valid())
                allf.append(forms[x][1].is_valid())
            else:
                pass
        curinstprofform=InstProfileForm(request.POST,prefix="cur")
        form=CreateCourseForm(request.POST)
        if all([curinstprofform.is_valid(), form.is_valid()]) and all(allf):
            curinst=curinstprofform.save(commit=False)
            curinst.user=request.user
            curinst.save()
            course=form.save(commit=False)
            if 'fulltext' in request.FILES:
                course.fulltext = request.FILES['fulltext']
            course.save()
            for key,f in forms.items():
                instx=f[0].save(commit=False)
                passwd=userops.generatenewpass(8)
                instx.set_password(passwd)
                instx.save()
                instxprof=f[1].save(commit=False)
                instxprof.user=instx
                instxprof.save()
                course.trainer.add(instxprof)
            course.trainer.add(curinst)
            course.save()
            note="Egitim oneriniz basari ile alindi."
        else:
            note="Olusturulamadi"
    return render_to_response("training/submitandregister.html",{'site':site,'pages':pages,'note':note,'form':form,'curinstprofform':curinstprofform,'forms':forms},context_instance=RequestContext(request))

@login_required
def new_course(request):
    return HttpResponse("Yeni kurs kaydi")

@login_required
@user_passes_test(active_required, login_url=reverse_lazy("active_resend"))
def show_course(request, course_id):
    try:
        data = prepare_template_data(request)    
        course = Course.objects.get(id=course_id)
        data['course'] = course
        return render_to_response('training/course_detail.html', data)
    except ObjectDoesNotExist:
        return HttpResponse("Kurs Bulunamadi")

@login_required
@user_passes_test(active_required, login_url=reverse_lazy("active_resend"))
def list_courses(request):
    data = prepare_template_data(request)
    courses = Course.objects.filter(site=data['site'])
    data['courses'] = courses
    return render_to_response('training/courses.html', data)    

@login_required
def edit_course(request):
    return HttpResponse("Yeni kurs kaydi")

@login_required
def apply_to_course(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    data=prepare_template_data(request)
    userprofile=None
    try:
        userprofile = UserProfile.objects.get(user=request.user)
    except ObjectDoesNotExist:
        return redirect("createprofile")
    if userprofile.userpassedtest:
        data['closed'] = "0"
        data['additional1_pref_closed'] = "1"
        data['PREFERENCE_LIMIT'] = PREFERENCE_LIMIT
        data['ADDITION_PREFERENCE_LIMIT'] = ADDITION_PREFERENCE_LIMIT
        message = ""
        now = datetime.date(datetime.now())
        note = _("You can choose courses in order of preference.")
        if request.method == "POST":
            if now < data['site'].application_start_date:
                message = _("You can choose courses in future")
                data['closed'] = True
                return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
            elif now > data['site'].application_end_date:
                message = _("The course choosing process is closed")
                data['closed'] = True
                return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
            TrainessCourseRecord.objects.filter(trainess=userprofile).delete()
            course_prefs = json.loads(request.POST.get('course'))
            if len(course_prefs) <= PREFERENCE_LIMIT:
                if len(set([i['value'] for i in course_prefs])) == len([i['value'] for i in course_prefs]):
                    for course_pre in course_prefs:
                        try:
                            course_record = TrainessCourseRecord(trainess=userprofile, 
                                                  course=Course.objects.get(id=course_pre['value']), 
                                                  preference_order=course_pre['name'])
                            course_record.save()
                            message = "Tercihleriniz başarılı bir şekilde güncellendi"
                        except Exception as e:
                            log.error(e.message, extra = d)
                            message = "Tercihleriniz kaydedilirken hata oluştu"
                            return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
                else:
                    message = "Farklı Tercihlerinizde Aynı Kursu Seçemezsiniz"
                    return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
                try:
                    context={}
                    context['user'] = request.user
                    domain = Site.objects.get(is_active=True).home_url
                    if domain.endswith('/'):
                        domain = domain.rstrip('/')
                    context['domain'] = domain
 
                    send_email("training/messages/preference_saved_subject.html",
                                 "training/messages/preference_saved.html",
                                 "training/messages/preference_saved.text",
                                 context,
                                 EMAIL_FROM_ADDRESS,
                                 [request.user.username])
                except Exception as e:
                    log.error(e.message, extra = d)
 
                return HttpResponse(json.dumps({'status':'0', 'message':message}), content_type="application/json")
            else:
                message = "En fazla " + PREFERENCE_LIMIT + " tane tercih hakkına sahipsiniz"
                return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
        
      
        additipnal_pref_start_for_trainess = ApprovalDate.objects.get(site=data['site'], preference_order=1, for_instructor=True ).start_date
        courses = Course.objects.filter(approved=True)
        course_records = TrainessCourseRecord.objects.filter(trainess__user=request.user).order_by('preference_order')
        data['courses'] = courses
        data['course_records'] = course_records
        data['note'] = note
        if now < data['site'].application_start_date:
            data['note'] = _("You can choose courses in future")
            data['closed'] = "1"
            return render_to_response('training/courserecord.html', data)
        elif now > data['site'].application_end_date:
            data['note'] = _("The course choosing process is closed")
            data['closed'] = "1"
            if len(TrainessCourseRecord.objects.filter(trainess_approved=True).filter(preference_order__gte=0).filter(trainess=userprofile)) == 0:
                try:
                    additional1_pref_for_trainess = ApprovalDate.objects.get(
    									                                   site=data['site'],
                                                                           preference_order=-1,
                                                                           for_trainess=True)
                    now_for_pref = timezone.now()
                    if now_for_pref > additional1_pref_for_trainess.start_date and now_for_pref < additional1_pref_for_trainess.end_date:
                        data['additional1_pref_closed'] = "0"
                        log.debug("ek tercih aktif", extra = d)
                        data['note'] = _("Ek tercih dönemi içindesiniz, ek tercih yapabilirsiniz")
                except ObjectDoesNotExist:
                    log.error("ek tercih icin sure bulunamadi", extra = d)
                except Exception as e:
                    log.error(e.message, extra = d)
            return render_to_response('training/courserecord.html', data) 
        return render_to_response('training/courserecord.html', data)
    else:
        return redirect("testbeforeapply")


@login_required
def control_panel(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    data = prepare_template_data(request)
    note = _("You can accept trainees")
    try:
        uprofile = UserProfile.objects.get(user=request.user).is_student
        log.info(uprofile, extra = d)
        if not uprofile:    
            courses = Course.objects.filter(approved=True).filter(trainer__user=request.user)
            log.info(courses, extra = d)
            if courses:
                log.info("egitmenin " + str(len(courses)) + " tane kursu var", extra=d)
                trainess = {}
                now_for_approve = timezone.now()
                log.debug("now_for_approve : egitmen kendi kursunu listeliyor", extra=d)
                log.debug(now_for_approve, extra=d)
                first_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=1,for_instructor=True ).start_date
                first_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=1, for_instructor=True).end_date
                second_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=2, for_instructor=True).start_date
                second_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=2, for_instructor=True).end_date
                third_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=3, for_instructor=True).start_date
                third_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=3, for_instructor=True).end_date
                addition1_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=-1, for_instructor=True).start_date
                addition1_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=-1, for_instructor=True).end_date
                note = "  1. Tercihleri %s - %s tarihleri arasında onaylayabilirsiniz" % (
                                     first_pref_approve_start.strftime(DATETIME_FORMAT),
                                     first_pref_approve_end.strftime(DATETIME_FORMAT)) + "  "
                note += "  2. Tercihten %s - %s tarihleri arasında seçebilirsiniz" % (
                                     second_pref_approve_start.strftime(DATETIME_FORMAT),
                                     second_pref_approve_end.strftime(DATETIME_FORMAT)) + "  "
                note += "  3. Tercihten %s - %s tarihleri arasında seçebilirsiniz" % (
                                     third_pref_approve_start.strftime(DATETIME_FORMAT),
                                     third_pref_approve_end.strftime(DATETIME_FORMAT)) + "  "
                data['closed_pref_1'] = "1"
                data['closed_pref_2'] = "1"
                data['closed_pref_3'] = "1"
                data['closed_pref_addition1'] = "1"
                data['note_edit_closed'] = "1"
                if (now_for_approve > first_pref_approve_start and now_for_approve < addition1_pref_approve_end):
                    if ((now_for_approve > first_pref_approve_start) and (now_for_approve < first_pref_approve_end)):
                        data['closed_pref_1'] = "0"
                    if ((now_for_approve > second_pref_approve_start) and (now_for_approve < second_pref_approve_end)):
                        data['closed_pref_2'] = "0"
                    if ((now_for_approve > third_pref_approve_start) and (now_for_approve < third_pref_approve_end)):
                        data['closed_pref_3'] = "0"
                    if ((now_for_approve > addition1_pref_approve_start) and (now_for_approve < addition1_pref_approve_end)):
                        data['closed_pref_addition1'] = "0"
                if (now_for_approve > addition1_pref_approve_end):
                    data['note_edit_closed'] = "0"
                for course in courses:
                    trainess[course] = {}
                    if (now_for_approve < ApprovalDate.objects.get(site=data['site'], preference_order=-1, for_trainess=True).end_date):
                        trainess[course]['trainess1'] = TrainessCourseRecord.objects.filter(
                                                                         course=course.pk).filter(
                                                                         preference_order=1).exclude(
                                                                         trainess__in = TrainessCourseRecord.objects.values_list('trainess').filter(
                                                                        ~Q(course=course.pk)).filter(
                                                                         trainess_approved=True)).prefetch_related('course')
                        trainess[course]['trainess2'] = TrainessCourseRecord.objects.filter(
                                                                         course=course.pk).filter(
                                                                         preference_order=2).exclude(
                                                                         trainess__in = TrainessCourseRecord.objects.values_list('trainess').filter(
                                                                        ~Q(course=course.pk)).filter(
                                                                         trainess_approved=True)).prefetch_related('course')
                        trainess[course]['trainess3'] = TrainessCourseRecord.objects.filter(
                                                                         course=course.pk).filter(
                                                                         preference_order=3).exclude(
                                                                         trainess__in = TrainessCourseRecord.objects.values_list('trainess').filter(
                                                                        ~Q(course=course.pk)).filter(
                                                                         trainess_approved=True)).prefetch_related('course')
                        trainess[course]['trainess_addition_1'] = TrainessCourseRecord.objects.filter(
                                                                         course=course.pk).filter(
                                                                         preference_order=-1).exclude(
                                                                         trainess__in = TrainessCourseRecord.objects.values_list('trainess').filter(
                                                                        ~Q(course=course.pk)).filter(
                                                                         trainess_approved=True)).prefetch_related('course')
                    else:
                        trainess[course]['trainess1'] = TrainessCourseRecord.objects.filter(
                                                                 course=course.pk).filter(
                                                                 preference_order=1).filter(
                                                                 approved=True).filter(trainess_approved=True).prefetch_related('course')
                        trainess[course]['trainess2'] = TrainessCourseRecord.objects.filter(
                                                                 course=course.pk).filter(
                                                                 preference_order=2).filter(
                                                                 approved=True).filter(trainess_approved=True).prefetch_related('course')
                        trainess[course]['trainess3'] = TrainessCourseRecord.objects.filter(
                                                                 course=course.pk).filter(
                                                                 preference_order=3).filter(
                                                                 approved=True).filter(trainess_approved=True).prefetch_related('course')
                        trainess[course]['trainess_addition_1'] = TrainessCourseRecord.objects.filter(
                                                                 course=course.pk).filter(
                                                                 preference_order=-1).filter(
                                                                 approved=True).filter(trainess_approved=True).prefetch_related('course')
                data['trainess'] = trainess
                if request.POST:
                    log.info("kursiyer onay islemi basladi", extra=d)
                    log.info(request.POST, extra=d)
                    for course in courses:
                        try:
                            if (now_for_approve > first_pref_approve_start and now_for_approve < third_pref_approve_end):
                                allprefs = []
                                if ((now_for_approve > first_pref_approve_start) and (now_for_approve < first_pref_approve_end)):
                                    allprefs.extend(TrainessCourseRecord.objects.filter(course=course.pk).filter(preference_order=1))
                                    log.debug(allprefs, extra=d)
                                if ((now_for_approve > second_pref_approve_start) and (now_for_approve < second_pref_approve_end)):
                                    allprefs.extend(TrainessCourseRecord.objects.filter(course=course.pk).filter(preference_order=2))
                                    log.debug(allprefs, extra=d)
                                if ((now_for_approve > third_pref_approve_start) and (now_for_approve < third_pref_approve_end)):
                                    allprefs.extend(TrainessCourseRecord.objects.filter(course=course.pk).filter(preference_order=3))
                                    log.debug(allprefs, extra=d)
                                approvedr = request.POST.getlist('students' + str(course.pk))
                                log.debug(allprefs, extra=d)
                                for p in allprefs:
                                    if str(p.pk) not in approvedr: 
                                        p.approved=False
                                    elif str(p.pk) in approvedr:
                                        p.approved=True
                                    p.save()
                                    log.debug(p, extra=d)
                                course.trainess.clear()
                                allprefs=TrainessCourseRecord.objects.filter(course=course.pk)
                                for p in allprefs:
                                    if p.approved == True:
                                        course.trainess.add(p.trainess)
                                course.save()

                                data["user"]=request.user
                                data["course"]=course
                                send_email("training/messages/inform_trainers_about_changes_subject.txt",
                                     "training/messages/inform_trainers_about_changes.html",
                                     "training/messages/inform_trainers_about_changes.txt",
                                     data,
                                     EMAIL_FROM_ADDRESS,
                                     course.trainer.all().values_list('user__username',flat=True))

                                note = "Seçimleriniz başarılı bir şekilde kaydedildi."
                            else:
                                if(now_for_approve > addition1_pref_approve_start) and (now_for_approve < addition1_pref_approve_end):
                                    allprefs = []
                                    allprefs.extend(TrainessCourseRecord.objects.filter(course=course.pk).filter(preference_order=-1))
                                    approvedr = request.POST.getlist('students' + str(course.pk))
                                    log.debug(allprefs, extra=d)
                                    for p in allprefs:
                                        if str(p.pk) not in approvedr: 
                                            p.approved = False
                                        elif str(p.pk) in approvedr:
                                            p.approved = True
                                            p.trainess_approved = True
                                        p.save()
                                        log.debug(p, extra=d)
                                    course.trainess.clear()
                                    allprefs = TrainessCourseRecord.objects.filter(course=course.pk)
                                    for p in allprefs:
                                        if p.approved == True:
                                            course.trainess.add(p.trainess)
                                    course.save()

                                    data["user"]=request.user
                                    data["course"]=course
                                    send_email("training/messages/inform_trainers_about_changes_subject.txt",
                                         "training/messages/inform_trainers_about_changes.html",
                                         "training/messages/inform_trainers_about_changes.txt",
                                         data,
                                         EMAIL_FROM_ADDRESS,
                                         course.trainer.all().values_list('user__username',flat=True))

                                    note = "Seçimleriniz başarılı bir şekilde kaydedildi."
                                else:    
                                    note = "Onaylama dönemi dışındasınız" 
                        except Exception as e:
                            note = "Beklenmedik bir hata oluştu!"
                            log.error(e.message, extra=d)
            data['TRAINESS_SCORE'] = TRAINESS_SCORE
            data['note'] = note
            return render_to_response("training/controlpanel.html", data, context_instance=RequestContext(request))
        else:
            return redirect("applytocourse")
    except UserProfile.DoesNotExist:
        return redirect("createprofile")

@staff_member_required
def allcourseprefview(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    data = prepare_template_data(request)
    data['datalist']=TrainessCourseRecord.objects.all()
    return render_to_response("training/allcourseprefs.html",data,context_instance=RequestContext(request))



@staff_member_required
def statistic(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    try:
        data=prepare_template_data(request)
    
        record_data = TrainessCourseRecord.objects.filter().values(
                                            'course','preference_order').annotate(
                                              Count('preference_order')).order_by(
                                               'course','-preference_order')
        statistic_by_course = {}
        for key, group in itertools.groupby(record_data, lambda item: item["course"]):
            course_object = Course.objects.get(pk=key)
            statistic_by_course[course_object] = {str(item['preference_order']):item['preference_order__count'] for item in group}
            statistic_by_course[course_object]['total_apply'] = len(TrainessCourseRecord.objects.filter(
                                                                                  course=course_object))
            statistic_by_course[course_object]['total_apply_by_trainer'] = len(TrainessCourseRecord.objects.filter(
                                                                                  course=course_object).filter(
                                                                                  approved=True))
            statistic_by_course[course_object]['total_apply_by_trainess'] = len(TrainessCourseRecord.objects.filter(
                                                                                  course=course_object).filter(
                                                                                  approved=True).filter(
                                                                                  trainess_approved=True))
            
            
        data['statistic_by_course'] = statistic_by_course
        statistic_by_gender = UserProfile.objects.filter(is_student=True).values('gender').annotate(Count('gender')).order_by('gender')
        data['statistic_by_gender'] = statistic_by_gender
        statistic_by_gender_for_approved = UserProfile.objects.filter(is_student=True).filter(
                                                              trainesscourserecord__approved__in=[True]).filter(
                                                              trainesscourserecord__trainess_approved__in=[True]).values('gender').annotate(Count('gender')).order_by('gender')
        data['statistic_by_gender_for_approved'] = statistic_by_gender_for_approved
        log.debug(statistic_by_gender,extra=d) 
        statistic_by_university = UserProfile.objects.filter(is_student=True).values('university').annotate(Count('university')).order_by('-university__count')
        data['statistic_by_university'] = statistic_by_university
        
        statistic_by_university_for_approved = UserProfile.objects.filter(is_student=True).values('university').filter(
                                                              trainesscourserecord__approved__in=[True]).filter(
                                                              trainesscourserecord__trainess_approved__in=[True]).annotate(Count('university')).order_by('-university__count')
        data['statistic_by_university_for_approved'] = statistic_by_university_for_approved

        #kurs bazinda toplam teyitli olanlar
        data['statistic_by_course_for_apply'] = TrainessCourseRecord.objects.filter(trainess_approved=True).values('course__name').annotate(count=Count('course')).order_by('-count')
        total_profile = len(UserProfile.objects.filter(is_student=True))
        total_preference = len(TrainessCourseRecord.objects.all())
        total_preference_for_approved = len(TrainessCourseRecord.objects.filter(approved=True).filter(trainess_approved=True))
        data['statistic_by_totalsize'] = {'Toplam Profil(Kişi)': total_profile, 'Toplam Tercih': total_preference, 'Toplam Teyit Eden': total_preference_for_approved}
    except Exception as e:
        log.error(e.message, extra=d)
    return render_to_response("training/statistic.html", data)

@login_required
def cancel_all_preference(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    if request.POST:
        try:
            data=prepare_template_data(request)
            userprofile = UserProfile.objects.get(user=request.user)
            trainess_course_records = TrainessCourseRecord.objects.filter(trainess=userprofile)
            context = {}
            for tcr in trainess_course_records:
                try:
                    # x. tercih onaylama donemi baslangic zamani ile x. tercih teyit etme donemi arasinda ise mail atsin.
                    now_for_approve = timezone.now()
                    preference_order = tcr.preference_order
                    check_start = ApprovalDate.objects.get(site=data['site'], preference_order=preference_order, for_instructor=True).start_date
                    check_end = ApprovalDate.objects.get(site=data['site'], preference_order=preference_order, for_trainess=True).end_date
                    if ((now_for_approve > check_start and now_for_approve < check_end) or (tcr.trainess_approved == True)):
                        context['trainess_course_record'] = tcr
                        send_email("training/messages/notice_for_canceled_courses_subject.html",
                                       "training/messages/notice_for_canceled_courses.html",
                                       "training/messages/notice_for_canceled_courses.text",
                                        context,
                                        EMAIL_FROM_ADDRESS,
                                        tcr.course.trainer.all().values_list('user__username',flat=True))
                except Exception as e:
                    log.error(e.message, extra=d)
                trainess_course_records.delete()
            message = "Tüm Başvurularınız Silindi"
            log.debug(message, extra=d)
        except ObjectDoesNotExist:
            message = "Başvurularınız Silinirken Hata Oluştu"
        except Exception as e:
            message = "Başvurularınız Silinirken Hata Oluştu"
            log.error(e.message, extra=d) 
        return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
    message = "Başvurularınız Silinirken Hata Oluştu"
    return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")

# 52 numarali issue ile kapatildi
#@login_required
#def cancel_course_application(request):
#    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
#    message = ""
#    status = "-1"
#    if request.POST:
#        try:
#            course = Course.objects.get(id=request.POST.get("course"), approved=True, trainer__user=request.user)
#            if request.POST.get("isOpen") == "true":
#                course.application_is_open = True
#                message = "Bu Kurs İçin Başvurular Açıldı"
#                status = "0"
#            else: 
#                course.application_is_open = False
#                message = "Bu Kurs İçin Başvurular Kapandı"
#                status = "0"
#            course.save()
#        except ObjectDoesNotExist:
#            message = "İşleminiz Sırasında Hata Oluştu"
#            status = "-1"
#        except Exception as e:
#            message = "İşleminiz Sırasında Hata Oluştu"
#            status = "-1"
#            log.error(e.message, extra=d) 
#        return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
#    message = "İşleminiz Sırasında Hata Oluştu"
#    return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")


@login_required
def approve_course_preference(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    data=prepare_template_data(request)
    now_for_approve = timezone.now()
    if request.POST:
        try:
            log.debug(request.POST.get("courseRecordId"), extra=d)
            trainess_course_record = TrainessCourseRecord.objects.get(trainess=request.user.userprofile, 
                                                                        approved=True, 
                                                                        id=request.POST.get("courseRecordId"))
            preference_order = trainess_course_record.preference_order
            pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=preference_order, for_trainess=True).start_date
            pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=preference_order, for_trainess=True).end_date
            if now_for_approve > pref_approve_start and now_for_approve < pref_approve_end:
                trainess_course_record.trainess_approved = True
                trainess_course_record.save()
                message = "İşleminiz başarılı bir şekilde gerçekleştirildi"
                status = "0"
                log.debug("kursu onayladi " + trainess_course_record.course.name, extra=d )
            else:
                message = "Kurs teyit dönemi dışındasınız."
                status = "-1"
        except Exception as e:
            log.error(e.message, extra=d)
            message = "İşleminiz Sırasında Hata Oluştu"
            status = "-1"
        return HttpResponse(json.dumps({'status':status, 'message':message}), content_type="application/json")
    
    try:
        first_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=1, for_trainess=True).start_date
        first_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=1, for_trainess=True).end_date
        second_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=2, for_trainess=True).start_date
        second_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=2, for_trainess=True).end_date
        third_pref_approve_start = ApprovalDate.objects.get(site=data['site'], preference_order=3, for_trainess=True).start_date
        third_pref_approve_end = ApprovalDate.objects.get(site=data['site'], preference_order=3, for_trainess=True).end_date
        trainess_course_record = []
        trainess_course_records = TrainessCourseRecord.objects.filter(trainess=request.user.userprofile).order_by('preference_order') 
        data['course_exist'] = "0"
        data['approve_is_open'] = "0"
        note = ""
        if now_for_approve > first_pref_approve_start and now_for_approve < third_pref_approve_end:
            if len(trainess_course_records) == len(trainess_course_records.filter(approved=False)):
                data['course_exist'] = "0"
                data['approve_is_open'] = "0"
                note = "Herhangi bir kursa kabul edilemediniz." 
                if first_pref_approve_start < now_for_approve and now_for_approve < second_pref_approve_start:
                    note = "Birinci tercihinizden herhangi bir kursa kabul edilemediniz varsa diğer tercihlerinizin sonuçlanmasını bekleyiniz"
                elif second_pref_approve_start < now_for_approve and now_for_approve < third_pref_approve_start:
                    note = "İkinci tercihinizden herhangi bir kursa kabul edilemediniz varsa diğer tercihlerinizin sonuçlanmasını bekleyiniz"
            elif len(trainess_course_records) == len(trainess_course_records.filter(trainess_approved=False)):
                data['course_exist'] = "1"
                data['approve_is_open'] = "1"
                note = "Kabul edildiğiniz aşağıdaki kursu onaylayabilirsiniz"
                if first_pref_approve_start < now_for_approve and now_for_approve < first_pref_approve_end:
                    trainess_course_record = trainess_course_records.filter(preference_order=1).filter(approved=True)
                elif second_pref_approve_start < now_for_approve and now_for_approve < second_pref_approve_end:
                    trainess_course_record = trainess_course_records.filter(preference_order=2).filter(approved=True)
                elif third_pref_approve_start < now_for_approve and now_for_approve < third_pref_approve_end:
                    trainess_course_record = trainess_course_records.filter(preference_order=3).filter(approved=True)
                if len(trainess_course_record) == 0:
                    note = "Kabul edildiğiniz veya teyit ettiğiniz kurs bulunamadı"
                    data['course_exist'] = "0"
                    data['approve_is_open'] = "0"
                 
            else:
                data['course_exist'] = "1"
                data['approve_is_open'] = "0"
                trainess_course_record = trainess_course_records.filter(trainess_approved=True).filter(approved=True)
                note = "Aşağıdaki Kursa Kabul Edildiniz"
        else:
            trainess_course_record = trainess_course_records.filter(trainess_approved=True).filter(approved=True)
            if len(trainess_course_record) == 1:
                data['course_exist'] = "1"
                data['approve_is_open'] = "0"
                note = "Aşağıdaki Kursa Kabul Edildiniz"
            else:
                if len(trainess_course_record) > 1:
                    log.debug("kursiyerin teyit edilen 1'den fazla kursu var!!", extra=d)
                note = "Kurs teyit dönemi dışındasınız veya kabul edildiğiniz kurs yok"
        data['note'] = note
        data['trainess_course_record'] = trainess_course_record
    except Exception as e:
            log.error(e.message, extra=d)
            data['note'] = "Hata oluştu"

    return render_to_response("training/confirm_course_preference.html", data)

 
            
    
@login_required
def get_preferred_courses(request):
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    message = ""
    status = "-1"
    if request.POST:
        preferred_courses = []
        try:
            course_records = TrainessCourseRecord.objects.filter(trainess__user=request.user).order_by('preference_order')
            preferred_courses = [course_record.course.name for course_record in course_records]
            status = "0"
        except Exception as e:
            message = "İşleminiz Sırasında Hata Oluştu"
            status = "-1"
            log.error(e.message, extra=d) 
        return HttpResponse(json.dumps({'status':status, 'preferred_courses': preferred_courses}), content_type="application/json")
    message = "İşleminiz Sırasında Hata Oluştu"
    return HttpResponse(json.dumps({'status':'-1'}), content_type="application/json")


def apply_course_in_addition(request):
    log.debug( request)
    d = {'clientip': request.META['REMOTE_ADDR'], 'user': request.user}
    if request.method == "POST":
        userprofile=None
        try:
            userprofile = UserProfile.objects.get(user=request.user)
        except ObjectDoesNotExist:
            return redirect("createprofile")
        TrainessCourseRecord.objects.filter(trainess=userprofile).delete()
        course_prefs = json.loads(request.POST.get('course'))
        if len(course_prefs) <= ADDITION_PREFERENCE_LIMIT:
            if len(set([i['value'] for i in course_prefs])) == len([i['value'] for i in course_prefs]):
                for course_pre in course_prefs:
                    try:
                        course_object = Course.objects.get(id=course_pre['value'])
                        if course_object.application_is_open:
                            course_record = TrainessCourseRecord(trainess=userprofile,
                                              course=course_object,
                                              preference_order=(-1)*int(course_pre['name']))
                            course_record.save()
                            log.debug("ek tercih kaydedildi " + str(course_pre['value']), extra = d)
                        else:
                            message = "Kurs basvurulara kapali"
                            log.error(message + " " + str(course_pre['value']), extra = d)
                    except Exception as e:
                        log.error(e.message, extra = d)
                        message = "Tercihleriniz kaydedilirken hata oluştu"
                        return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")
                message = "Tercihleriniz başarılı bir şekilde güncellendi"
                return HttpResponse(json.dumps({'status':'0', 'message':message}), content_type="application/json")
    message = "Tercih işlemi yapmanıza izin verilmiyor"
    return HttpResponse(json.dumps({'status':'-1', 'message':message}), content_type="application/json")

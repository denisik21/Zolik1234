from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.contrib.auth import authenticate, login, logout
from .models import Room, Topic, Message, User
from .forms import RoomForm, UserForm, MyUserCreationForm
import requests
from django.conf import settings
import threading


def loginPage(request):
    page = 'login'
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        email = request.POST.get('email').lower()
        password = request.POST.get('password')

        try:
            user = User.objects.get(email=email)
        except:
            messages.error(request, 'User does not exist')

        user = authenticate(request, email=email, password=password)

        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, "Username OR password does not exist")

    context = {'page': page}
    return render(request, 'base/login_register.html', context)


def logoutUser(request):
    logout(request)
    return redirect('home')


def registerPage(request):
    form = MyUserCreationForm()

    if request.method == 'POST':
        form = MyUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.username = user.username.lower()
            user.save()
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, 'An error occurred during registration')

    return render(request, 'base/login_register.html', {'form': form})


def home(request):
    q = request.GET.get('q') if request.GET.get('q') != None else ''
    rooms = Room.objects.filter(
        Q(topic__name__icontains=q) |
        Q(name__icontains=q) |
        Q(description__icontains=q)
        )

    topics = Topic.objects.all()
    room_count = rooms.count()
    room_messages = Message.objects.filter(Q(room__topic__name__icontains=q)).exclude(user__username='bot')

    context = {'rooms': rooms, 'topics': topics, 'room_count': room_count, 'room_messages': room_messages}
    return render(request, 'base/home.html', context)


def room(request, pk):
    room = Room.objects.get(id=pk)
    room_messages = room.message_set.all()
    participants = room.participants.all()

    if request.method == 'POST':
        message = Message.objects.create(
            user=request.user,
            room=room,
            body=request.POST.get('body')
        )
        room.participants.add(request.user)
        return redirect('room', pk=room.id)

    context = {'room': room, 'room_messages': room_messages, 'participants': participants}
    return render(request, 'base/room.html', context)


def userProfile(request, pk):
    user = User.objects.get(id=pk)
    rooms = user.room_set.all()
    room_messages = user.message_set.all()
    topics = Topic.objects.all()
    context = {'user': user, 'rooms': rooms, 'room_messages': room_messages, 'topics': topics}
    return render(request, 'base/profile.html', context)


@login_required(login_url='login')
def createRoom(request):
    form = RoomForm()
    topics = Topic.objects.all()

    if request.method == 'POST':
        topic_name = request.POST.get('topic')
        topic, created = Topic.objects.get_or_create(name=topic_name)

        # Создаем комнату
        room = Room.objects.create(
            host=request.user,
            topic=topic,
            name=request.POST.get('name'),
            description=request.POST.get('description')
        )

        # Получаем бота-пользователя
        bot_user, bot_created = User.objects.get_or_create(
            username='bot',
            defaults={
                'email': 'bot@example.com',
                'password': 'password',  # Задайте безопасный пароль
                'name': 'Chat Bot',
                'is_active': True
            }
        )

        # Добавляем бота в участники комнаты
        room.participants.add(bot_user)

        # Добавляем приветственное сообщение от бота
        Message.objects.create(
            user=bot_user,
            room=room,
            body='Здравствуйте, я bot и вы можете ко мне обращаться.'
        )

        return redirect('home')

    context = {'form': form, 'topics': topics}
    return render(request, 'base/room_form.html', context)


def get_bot_response(message):
    prompt = {
        "modelUri": "gpt://b1gosh02ms10qpt62p0p/yandexgpt/latest",
        "completionOptions": {
            "stream": False,
            "temperature": 0.6,
            "maxTokens": "2000"
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты консультант по языкам программирования"
            },
            {
                "role": "user",
                "text": message
            }
        ]
    }

    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {settings.YANDEX_API_KEY}"
    }

    response = requests.post(url, headers=headers, json=prompt)
    
    print("Response status code:", response.status_code)
    print("Response content:", response.content)
    
    result = response.json()
    
    # Проверка, содержит ли ответ ключ 'alternatives'
    if 'result' in result and 'alternatives' in result['result']:
        return result['result']['alternatives'][0]['message']['text']
    else:
        return "Извините, произошла ошибка при получении ответа от бота."

@login_required(login_url='login')
def send_message(request, room_id):
    if request.method == 'POST':
        message_body = request.POST['body']
        room = Room.objects.get(id=room_id)
        message = Message.objects.create(
            user=request.user,
            room=room,
            body=message_body
        )
        room.participants.add(request.user)

        # Проверяем, начинается ли сообщение с "@bot,"
        if message_body.strip().startswith("@bot,"):
            # Запуск фонового потока для получения ответа от бота
            threading.Thread(target=handle_bot_response, args=(message_body[len("@bot,"):].strip(), room)).start()

        return redirect('room', pk=room_id)
    else:
        return redirect('home')

def handle_bot_response(message_body, room):
    bot_response = get_bot_response(message_body)

    # Создание сообщения от бота
    bot_user = User.objects.get(username='bot')
    Message.objects.create(
        user=bot_user,
        room=room,
        body=bot_response
    )


@login_required(login_url='login')
def updateRoom(request, pk):
    room = Room.objects.get(id=pk)
    form = RoomForm(instance=room)
    topics = Topic.objects.all()
    if request.user != room.host:
        return HttpResponse('Your are not allowed here!!')

    if request.method == 'POST':
        topic_name = request.POST.get('topic')
        topic, created = Topic.objects.get_or_create(name=topic_name)
        room.name = request.POST.get('name')
        room.topic = topic
        room.description = request.POST.get('description')
        room.save()
        return redirect('home')

    context = {'form': form, 'topics': topics, 'room': room}
    return render(request, 'base/room_form.html', context)


@login_required(login_url='login')
def deleteRoom(request, pk):
    room = Room.objects.get(id=pk)

    if request.user != room.host:
        return HttpResponse('Your are not allowed here!!')

    if request.method == 'POST':
        room.delete()
        return redirect('home')
    return render(request, 'base/delete.html', {'obj':room})


@login_required(login_url='login')
def deleteMessage(request, pk):
    message = Message.objects.get(id=pk)

    if request.user != message.user:
        return HttpResponse('Your are not allowed here!!')

    if request.method == 'POST':
        message.delete()
        return redirect('home')
    return render(request, 'base/delete.html', {'obj':message})


@login_required(login_url='login')
def updateUser(request):
    user = request.user
    form = UserForm(instance=user)

    if request.method == 'POST':
        form = UserForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            return redirect('user-profile', pk=user.id)

    return render(request, 'base/update-user.html', {'form': form})
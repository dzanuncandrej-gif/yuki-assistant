from pathlib import Path

import pytest

from core import commands, playlist


@pytest.fixture()
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(playlist, "PATH", tmp_path / "playlist.json")
    music = tmp_path / "music"
    (music / "rock").mkdir(parents=True)
    for name in ("Imagine Dragons - Believer (Official Video).mp3", "01 Кино – Группа крови.flac",
                 "rock/Linkin_Park - Numb.mp3", "notes.txt"):
        (music / name).write_bytes(b"x")
    return music


class FakePlayer:
    def __init__(self):
        self.calls = []
        self.track = None

    def play(self, index, shuffle=False):
        self.calls.append(("play", index, shuffle))
        self.track = playlist.tracks()[index]

    def toggle(self):
        self.calls.append(("toggle",))

    def stop(self):
        self.track = None

    def step(self, offset):
        self.calls.append(("step", offset))

    def set_shuffle(self, value):
        pass

    def current(self):
        return self.track

    def playing(self):
        return self.track is not None

    def active(self):
        return self.track is not None


@pytest.fixture()
def player(monkeypatch):
    fake = FakePlayer()
    monkeypatch.setattr(playlist, "_player", fake)
    return fake


def test_names_come_from_file_names():
    track = playlist.describe(Path("Imagine Dragons - Believer (Official Video).mp3"))
    assert (track.artist, track.title) == ("Imagine Dragons", "Believer")
    track = playlist.describe(Path("01 Кино – Группа крови.flac"))
    assert (track.artist, track.title) == ("Кино", "Группа крови")
    assert playlist.describe(Path("Linkin_Park - Numb.mp3")).artist == "Linkin Park"


def test_add_folder_takes_audio_only_and_skips_duplicates(library):
    assert playlist.add([library]) == 3
    assert playlist.add([library / "rock" / "Linkin_Park - Numb.mp3"]) == 0
    assert {track.title for track in playlist.tracks()} == {"Believer", "Группа крови", "Numb"}


def test_remove_and_move(library):
    playlist.add([library])
    first, second = playlist.tracks()[:2]
    playlist.move(second.path, -1)
    assert playlist.tracks()[0].path == second.path
    playlist.remove(first.path)
    assert first.path not in {track.path for track in playlist.tracks()}


def test_play_by_name(library, player):
    playlist.add([library])
    answer = playlist.play("believer")
    assert "Believer" in answer
    assert player.calls[-1][0] == "play"


def test_empty_playlist_explains_what_to_do(library, player):
    with pytest.raises(playlist.PlaylistError, match="пуст"):
        playlist.play()


def test_media_control_goes_to_own_player_when_active(library, player):
    from core import media

    playlist.add([library])
    playlist.play()
    assert media.control("next").startswith("включила")
    assert player.calls[-1] == ("step", 1)
    assert media.stop() == "выключила"
    assert not playlist.active()


@pytest.mark.parametrize("phrase", [
    "включи мою любимую музыку",
    "включи мою музыку",
    "поставь мои любимые песни",
    "включи мой плейлист",
    "включи плейлист вперемешку",
    "включи что-нибудь из моего плейлиста",
    "перемешай",
])
def test_voice_phrases_reach_playlist(phrase):
    assert commands.match_intent(phrase) == "playlist"


@pytest.mark.parametrize("phrase", ["включи музыку Believer", "включи видео про котиков"])
def test_other_music_requests_stay_where_they_were(phrase):
    assert commands.match_intent(phrase) != "playlist"

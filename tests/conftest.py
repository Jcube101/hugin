import pytest


@pytest.fixture
def valid_mood_params():
    return {
        "genres": [35, 18],
        "keywords": ["witty", "clever dialogue"],
        "vote_floor": 7.0,
        "gem_mode": False,
        "sort_by": "vote_average.desc",
    }


@pytest.fixture
def mock_movie():
    return {
        "id": 914,
        "title": "The Great Dictator",
        "overview": "A barber fights back.",
        "poster_path": "/poster.jpg",
        "release_date": "1940-10-15",
        "vote_average": 8.28,
        "vote_count": 3677,
        "genre_ids": [35],
        "adult": False,
        "backdrop_path": "/backdrop.jpg",
        "original_language": "en",
        "original_title": "The Great Dictator",
        "popularity": 6.88,
        "video": False,
    }


@pytest.fixture
def mock_movie_detail():
    return {
        "imdb_id": "tt0032553",
        "runtime": 125,
        "tagline": "Once again - the whole world laughs!",
        "genres": ["Comedy"],
    }


@pytest.fixture
def mock_omdb_enrichment():
    return {
        "imdb_rating": "8.4",
        "rt_score": "92%",
        "rated": "G",
    }


@pytest.fixture
def mock_enriched_movie(mock_movie, mock_movie_detail, mock_omdb_enrichment):
    return {**mock_movie, **mock_movie_detail, **mock_omdb_enrichment}


@pytest.fixture
def mock_discover_response():
    base = {
        "overview": "A movie.",
        "poster_path": "/p.jpg",
        "release_date": "2020-01-01",
        "vote_average": 7.5,
        "vote_count": 500,
        "genre_ids": [35],
        "adult": False,
        "backdrop_path": "/b.jpg",
        "original_language": "en",
        "original_title": "Movie",
        "popularity": 10.0,
        "video": False,
    }
    return [
        {**base, "id": i + 1, "title": f"Movie {i + 1}"}
        for i in range(5)
    ]


@pytest.fixture
def mock_tmdb_detail_response():
    return {
        "imdb_id": "tt1234567",
        "runtime": 120,
        "tagline": "A great film.",
        "genres": [{"id": 35, "name": "Comedy"}, {"id": 18, "name": "Drama"}],
    }

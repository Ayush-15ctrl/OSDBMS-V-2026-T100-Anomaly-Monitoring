"""OS/DBMS concept: reproducible workload generation for offline evaluation."""

from dataclasses import dataclass
import random
from typing import Sequence


@dataclass(frozen=True)
class SyntheticSession:
    """Labeled behavior-only session for synthetic model training."""

    student_id: int
    session_id: str
    label: str
    events: list[dict[str, float | str]]


class SyntheticDataGenerator:
    """Generate seeded, student-specific behavior histories.

    Population parameters are sampled once per student and reused by every
    practice and exam session. Exam behaviors apply moderate deviations to a
    fixed fraction of questions, preserving overlap with honest behavior.

    The population draws use these fixed distributions: keystroke mean
    ``N(0.22, 0.025)`` with std ``0.03``; timing base mean ``N(27, 3)`` with
    std ``4.5`` and difficulty slope ``N(8, 0.8)``; focus mean ``N(0.09,
    0.02)`` with std ``0.025``; answer-change mean ``N(0.08, 0.02)`` with
    std ``0.025``; mouse entropy mean ``N(0.68, 0.07)`` with std ``0.08``;
    answer-count probability is the sampled mean ``N(0.7, 0.15)`` divided by
    five; navigation mean ``N(0.08, 0.02)`` with std ``0.025``. Values are
    clamped to zero, and difficulty is an integer from one through five.
    Exam deviations affect 35 percent of questions. Nervous behavior shifts
    selected means by 0.35, 0.5, and 0.4 of their student stds and multiplies
    noise by 1.8. Paste shifts key, time, and entropy by 1.5, 1.2, and 1.4
    stds. Friend-feeding reduces time by ``0.8 + 0.25*difficulty`` stds,
    reduces entropy by 1.2 stds, and raises focus switching by 0.9 stds.
    """

    def __init__(self, seed: int = 42) -> None:
        """Create a generator with a reproducible population seed."""
        self.seed = seed
        self._parameters: dict[int, dict[str, tuple[float, float]]] = {}

    def student_parameters(self, student_id: int) -> dict[str, tuple[float, float]]:
        """Return stable ``signal -> (mean, std)`` parameters for one student.

        Population distributions are deliberately overlapping. The
        ``time_slope`` entry controls difficulty scaling and is not itself a
        stored event signal.
        """
        student_id = int(student_id)
        if student_id not in self._parameters:
            generator = random.Random(f"{self.seed}:student:{student_id}")
            self._parameters[student_id] = {
                "keystroke_interval": (max(0.08, generator.gauss(0.22, 0.025)), 0.03),
                "time_per_question": (max(16.0, generator.gauss(27.0, 3.0)), 4.5),
                "focus_switch_rate": (max(0.01, generator.gauss(0.09, 0.02)), 0.025),
                "answer_change_rate": (max(0.01, generator.gauss(0.08, 0.02)), 0.025),
                "mouse_path_entropy": (max(0.2, generator.gauss(0.68, 0.07)), 0.08),
                "answer_change_count": (max(0.1, generator.gauss(0.7, 0.15)), 0.7),
                "navigation_order_deviation": (max(0.02, generator.gauss(0.08, 0.02)), 0.025),
                "time_vs_difficulty": (max(3.0, generator.gauss(7.0, 0.7)), 1.0),
                "time_slope": (max(3.0, generator.gauss(8.0, 0.8)), 0.8),
            }
        return dict(self._parameters[student_id])

    @staticmethod
    def _value(generator: random.Random, mean: float, std: float) -> float:
        """Draw a non-negative value from a normal distribution."""
        return max(0.0, generator.gauss(mean, std))

    def _session(self, student_id: int, session_number: int, behavior: str) -> SyntheticSession:
        """Generate one honest or partially deviating thirty-question session."""
        if behavior not in {"honest", "nervous", "paste", "friend_feeding"}:
            raise ValueError(f"unsupported behavior: {behavior}")
        parameters = self.student_parameters(student_id)
        generator = random.Random(f"{self.seed}:session:{student_id}:{session_number}:{behavior}")
        events: list[dict[str, float | str]] = []
        for _ in range(30):
            difficulty = generator.randint(1, 5)
            affected = behavior != "honest" and generator.random() < 0.35
            nervous_noise = 1.8 if behavior == "nervous" else 1.0
            key_mean, key_std = parameters["keystroke_interval"]
            time_mean, time_std = parameters["time_per_question"]
            focus_mean, focus_std = parameters["focus_switch_rate"]
            change_mean, change_std = parameters["answer_change_rate"]
            entropy_mean, entropy_std = parameters["mouse_path_entropy"]
            navigation_mean, navigation_std = parameters["navigation_order_deviation"]
            slope_mean, _ = parameters["time_slope"]

            if behavior == "nervous":
                key_mean += key_std * 0.35
                focus_mean += focus_std * 0.5
                change_mean += change_std * 0.4
            if affected and behavior == "paste":
                key_mean -= key_std * 1.5
                time_mean -= time_std * 1.2
                entropy_mean -= entropy_std * 1.4
            elif affected and behavior == "friend_feeding":
                time_mean -= time_std * (0.8 + 0.25 * difficulty)
                entropy_mean -= entropy_std * 1.2
                focus_mean += focus_std * 0.9

            key_gap = self._value(generator, key_mean, key_std * nervous_noise)
            question_time = self._value(
                generator,
                time_mean + slope_mean * difficulty,
                time_std * nervous_noise,
            )
            focus_rate = self._value(generator, focus_mean, focus_std * nervous_noise)
            change_rate = self._value(generator, change_mean, change_std * nervous_noise)
            entropy = self._value(generator, entropy_mean, entropy_std * nervous_noise)
            navigation = self._value(
                generator,
                navigation_mean,
                navigation_std * nervous_noise,
            )
            normalized_time = max(0.0, question_time / difficulty)
            count_probability = min(0.9, max(0.01, parameters["answer_change_count"][0] / 5))
            answer_count = int(generator.random() < count_probability)
            events.extend(
                [
                    {"signal": "question_difficulty", "value": difficulty},
                    {"signal": "keystroke_interval", "value": key_gap},
                    {"signal": "time_per_question", "value": question_time},
                    {"signal": "focus_switch_rate", "value": focus_rate},
                    {"signal": "answer_change_rate", "value": change_rate},
                    {"signal": "mouse_path_entropy", "value": entropy},
                    {"signal": "answer_change_count", "value": answer_count},
                    {"signal": "navigation_order_deviation", "value": navigation},
                    {"signal": "time_vs_difficulty", "value": normalized_time},
                ]
            )
        return SyntheticSession(
            student_id=student_id,
            session_id=f"{student_id}-{behavior}-{session_number}",
            label=behavior,
            events=events,
        )

    def _sessions(self, student_id: int, sessions: int, label: str) -> list[SyntheticSession]:
        """Generate sessions for an existing labeled compatibility method."""
        if sessions < 0:
            raise ValueError("sessions must be non-negative")
        behavior = {
            "normal": "honest",
            "nervous-honest": "nervous",
            "paste-burst": "paste",
            "friend-feeding": "friend_feeding",
        }[label]
        return [self._session(student_id, number, behavior) for number in range(sessions)]

    def practice_history(self, student_id: int, n: int) -> list[SyntheticSession]:
        """Return ``n`` honest practice sessions for one student."""
        if n < 0:
            raise ValueError("n must be non-negative")
        return [self._session(student_id, number, "honest") for number in range(n)]

    def exam_session(self, student_id: int, behavior: str) -> SyntheticSession:
        """Return one exam session with partial behavior-specific deviations."""
        return self._session(student_id, 10000, behavior)

    def normal_student(self, student_id: int, sessions: int = 5) -> list[SyntheticSession]:
        """Generate honest sessions for compatibility with the original API."""
        return self._sessions(student_id, sessions, "normal")

    def nervous_honest_student(self, student_id: int, sessions: int = 5) -> list[SyntheticSession]:
        """Generate nervous-but-honest sessions for compatibility."""
        return self._sessions(student_id, sessions, "nervous-honest")

    def paste_burst_student(self, student_id: int, sessions: int = 5) -> list[SyntheticSession]:
        """Generate paste-burst sessions for compatibility with the original API."""
        return self._sessions(student_id, sessions, "paste-burst")

    def friend_feeding_student(self, student_id: int, sessions: int = 5) -> list[SyntheticSession]:
        """Generate friend-feeding sessions for compatibility with the original API."""
        return self._sessions(student_id, sessions, "friend-feeding")

    def histories(self, student_ids: Sequence[int]) -> dict[int, list[SyntheticSession]]:
        """Generate deterministic labeled histories for the requested students."""
        profiles = (
            self.normal_student,
            self.nervous_honest_student,
            self.paste_burst_student,
            self.friend_feeding_student,
        )
        return {
            int(student_id): profiles[index % len(profiles)](int(student_id))
            for index, student_id in enumerate(student_ids)
        }

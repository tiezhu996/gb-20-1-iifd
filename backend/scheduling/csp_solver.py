import random
import uuid
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict


# 上午固定为前 4 节，其余为下午；连堂不允许跨越这个边界
MORNING_PERIOD_COUNT = 4


@dataclass
class TimeSlot:
    day: int
    period: int

    def __hash__(self):
        return hash((self.day, self.period))

    def __eq__(self, other):
        return self.day == other.day and self.period == other.period


@dataclass
class SchedulingTask:
    class_id: int
    course_id: int
    teacher_id: int
    weekly_hours: int
    preferred_room_type: str
    priority: str
    available_time_slots: List[TimeSlot]
    classroom_capacity: int
    course_name: str = ''
    consecutive_periods: int = 1


@dataclass
class BlockSuggestion:
    """无法整组落下的连堂课组及排课建议。"""
    day: int
    periods: List[int]
    reason: str


class CSPScheduler:
    def __init__(self, semester):
        self.semester = semester
        self.weekly_days = semester.weekly_days
        self.daily_periods = len(semester.daily_periods) if semester.daily_periods else 7
        self.morning_len = min(MORNING_PERIOD_COUNT, self.daily_periods)
        self.afternoon_len = max(0, self.daily_periods - self.morning_len)
        self.all_slots = [
            TimeSlot(day=d + 1, period=p + 1)
            for d in range(self.weekly_days)
            for p in range(self.daily_periods)
        ]
        self.classroom_usage = defaultdict(set)
        self.teacher_usage = defaultdict(set)
        self.class_usage = defaultdict(set)
        self.assignments = []
        self.conflicts = []

    def build_session_windows(self, size: int) -> Tuple[List[List[TimeSlot]], List[List[TimeSlot]]]:
        """生成所有能容纳 size 连排节数的连续窗口，上午、下午分别成组，不跨边界。"""
        morning_windows = []
        afternoon_windows = []
        for day in range(1, self.weekly_days + 1):
            if size <= self.morning_len:
                for start in range(1, self.morning_len - size + 2):
                    morning_windows.append(
                        [TimeSlot(day=day, period=start + i) for i in range(size)]
                    )
            afternoon_start = self.morning_len + 1
            if size <= self.afternoon_len:
                for start in range(afternoon_start,
                                   afternoon_start + self.afternoon_len - size + 1):
                    afternoon_windows.append(
                        [TimeSlot(day=day, period=start + i) for i in range(size)]
                    )
        random.shuffle(morning_windows)
        random.shuffle(afternoon_windows)
        return morning_windows, afternoon_windows

    def candidate_windows(self, size: int, priority: str) -> List[List[TimeSlot]]:
        """按优先级给出候选窗口顺序：主科优先上午，副科优先下午，中级随机打散。"""
        morning_windows, afternoon_windows = self.build_session_windows(size)
        if priority == 'high':
            return morning_windows + afternoon_windows
        elif priority == 'low':
            return afternoon_windows + morning_windows
        windows = morning_windows + afternoon_windows
        random.shuffle(windows)
        return windows

    def is_available(
        self,
        time_slot: TimeSlot,
        teacher_id: int,
        class_id: int,
        classroom_id: int,
        teacher_available_slots
    ) -> bool:
        if teacher_available_slots is not None and time_slot not in teacher_available_slots:
            return False
        if time_slot in self.teacher_usage[teacher_id]:
            return False
        if time_slot in self.class_usage[class_id]:
            return False
        if time_slot in self.classroom_usage[classroom_id]:
            return False
        return True

    def find_room_for_window(
        self,
        window: List[TimeSlot],
        teacher_id: int,
        class_id: int,
        compatible_rooms: List[int],
        teacher_available_slots
    ) -> Optional[int]:
        """同一教室必须在课组的全部节次都空闲（同班级、教师和教室连续占住）。"""
        for room in compatible_rooms:
            if all(
                self.is_available(slot, teacher_id, class_id, room, teacher_available_slots)
                for slot in window
            ):
                return room
        return None

    def get_compatible_classrooms(
        self,
        preferred_room_type: str,
        required_capacity: int,
        classrooms_data: Dict[int, Dict]
    ) -> List[int]:
        compatible = []
        for cid, cdata in classrooms_data.items():
            if cdata['room_type'] == preferred_room_type and cdata['capacity'] >= required_capacity:
                compatible.append(cid)
        if not compatible:
            for cid, cdata in classrooms_data.items():
                if cdata['capacity'] >= required_capacity:
                    compatible.append(cid)
        return compatible

    @staticmethod
    def split_into_groups(weekly_hours: int, consecutive_periods: int) -> List[int]:
        """每周课时拆成完整连堂课组；除不尽时余下课时单独成组（不并入也不拆整组）。"""
        group_size = max(1, consecutive_periods)
        full, remainder = divmod(weekly_hours, group_size)
        return [group_size] * full + ([remainder] if remainder else [])

    def suggest_window(
        self,
        size: int,
        task: SchedulingTask,
        compatible_rooms: List[int],
        teacher_available_slots
    ) -> Optional[BlockSuggestion]:
        """在全部窗口中找冲突最少的一个，作为建议星期与节次返回。"""
        morning_windows, afternoon_windows = self.build_session_windows(size)
        windows = morning_windows + afternoon_windows
        if not windows:
            return None

        best_window = None
        best_score = None
        best_reason = ''
        for window in windows:
            class_busy = sum(1 for s in window if s in self.class_usage[task.class_id])
            teacher_unavailable = 0
            teacher_busy = 0
            if teacher_available_slots:
                teacher_unavailable = sum(1 for s in window if s not in teacher_available_slots)
            teacher_busy = sum(1 for s in window if s in self.teacher_usage[task.teacher_id])
            room_busy = None
            for room in compatible_rooms:
                busy = sum(1 for s in window if s in self.classroom_usage[room])
                if room_busy is None or busy < room_busy:
                    room_busy = busy
            room_busy = room_busy if room_busy is not None else size

            # 教师本身不可用的时段改不了，排在最后；其余按冲突节数挑最少的窗口
            score = (1 if teacher_unavailable else 0,
                     class_busy + teacher_busy + room_busy,
                     teacher_unavailable)
            if best_score is None or score < best_score:
                best_score = score
                best_window = window
                reasons = []
                if teacher_unavailable:
                    reasons.append(f'教师不可用 {teacher_unavailable} 节')
                if class_busy:
                    reasons.append(f'班级占用 {class_busy} 节')
                if teacher_busy:
                    reasons.append(f'教师占用 {teacher_busy} 节')
                if room_busy:
                    reasons.append(f'教室占用 {room_busy} 节')
                best_reason = '、'.join(reasons) if reasons else '时段紧张'

        periods = [s.period for s in best_window]
        return BlockSuggestion(
            day=best_window[0].day,
            periods=periods,
            reason=best_reason
        )

    def place_block(
        self,
        task: SchedulingTask,
        window: List[TimeSlot],
        room: int
    ) -> str:
        block_id = uuid.uuid4().hex if len(window) > 1 else ''
        for slot in window:
            self.classroom_usage[room].add(slot)
            self.teacher_usage[task.teacher_id].add(slot)
            self.class_usage[task.class_id].add(slot)
            self.assignments.append({
                'semester_id': self.semester.id,
                'class_id': task.class_id,
                'course_id': task.course_id,
                'teacher_id': task.teacher_id,
                'classroom_id': room,
                'day_of_week': slot.day,
                'period': slot.period,
                'block_id': block_id,
                'is_locked': False
            })
        return block_id

    def schedule(
        self,
        tasks: List[SchedulingTask],
        classrooms_data: Dict[int, Dict],
        teachers_data: Dict[int, Dict],
        locked_entries: Optional[List[Dict]] = None
    ) -> Tuple[List[Dict], List[Dict]]:
        self.assignments = []
        self.conflicts = []
        self.classroom_usage.clear()
        self.teacher_usage.clear()
        self.class_usage.clear()

        # 锁定课先占位
        if locked_entries:
            for entry in locked_entries:
                slot = TimeSlot(day=entry['day_of_week'], period=entry['period'])
                self.classroom_usage[entry['classroom_id']].add(slot)
                self.teacher_usage[entry['teacher_id']].add(slot)
                self.class_usage[entry['class_id']].add(slot)
                self.assignments.append(entry)

        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        sorted_tasks = sorted(
            tasks,
            key=lambda t: (priority_order[t.priority], -t.weekly_hours)
        )

        for task in sorted_tasks:
            # None 表示未配置可用时段（不限制）；非空集合才作为限制
            teacher_available = None
            avail_data = teachers_data.get(task.teacher_id, {}).get('available_time_slots')
            if avail_data:
                teacher_available = {
                    TimeSlot(day=slot_dict['day'], period=slot_dict['period'])
                    for slot_dict in avail_data
                }

            compatible_rooms = self.get_compatible_classrooms(
                task.preferred_room_type,
                task.classroom_capacity,
                classrooms_data
            )

            if not compatible_rooms:
                self.conflicts.append({
                    'type': 'classroom',
                    'task': f"班级{task.class_id}的课程{task.course_id}",
                    'course_name': task.course_name,
                    'message': f"{task.course_name}：没有找到适合 {task.preferred_room_type} 类型且容量足够的教室"
                })
                continue

            # 每周课时拆成完整课组（如 5 课时、连排 2 节 -> 2+2+1）
            group_sizes = self.split_into_groups(task.weekly_hours, task.consecutive_periods)

            for size in group_sizes:
                windows = self.candidate_windows(size, task.priority)

                if not windows:
                    self.conflicts.append({
                        'type': 'unplaced_block',
                        'task': f"班级{task.class_id}的课程{task.course_id}",
                        'course_name': task.course_name,
                        'class_id': task.class_id,
                        'group_size': size,
                        'day_of_week': None,
                        'periods': [],
                        'message': (
                            f"{task.course_name}（{size}节连堂）无法排课："
                            f"上午 {self.morning_len} 节、下午 {self.afternoon_len} 节，"
                            f"均放不下 {size} 节连续课组，请调小连排节数或增加每日节次"
                        )
                    })
                    continue

                placed = False
                for window in windows:
                    room = self.find_room_for_window(
                        window, task.teacher_id, task.class_id,
                        compatible_rooms, teacher_available
                    )
                    if room is not None:
                        self.place_block(task, window, room)
                        placed = True
                        break

                # 剩下的空档放不下整组时不拆开，记录课程、星期和建议节次
                if not placed:
                    suggestion = self.suggest_window(
                        size, task, compatible_rooms, teacher_available
                    )
                    if suggestion and suggestion.periods:
                        periods_text = (
                            f"第{suggestion.periods[0]}-{suggestion.periods[-1]}节"
                            if len(suggestion.periods) > 1
                            else f"第{suggestion.periods[0]}节"
                        )
                        message = (
                            f"{task.course_name}（{size}节连堂）本周没有完整的连续空档，"
                            f"建议安排到周{suggestion.day} {periods_text}"
                            f"（当前：{suggestion.reason}），可调整锁定课或其他课程后重排"
                        )
                        self.conflicts.append({
                            'type': 'unplaced_block',
                            'task': f"班级{task.class_id}的课程{task.course_id}",
                            'course_name': task.course_name,
                            'class_id': task.class_id,
                            'group_size': size,
                            'day_of_week': suggestion.day,
                            'periods': suggestion.periods,
                            'message': message
                        })
                    else:
                        self.conflicts.append({
                            'type': 'unplaced_block',
                            'task': f"班级{task.class_id}的课程{task.course_id}",
                            'course_name': task.course_name,
                            'class_id': task.class_id,
                            'group_size': size,
                            'day_of_week': None,
                            'periods': [],
                            'message': (
                                f"{task.course_name}（{size}节连堂）无法排入，"
                                f"没有可容纳 {size} 节连续课组的时段"
                            )
                        })

        return self.assignments, self.conflicts


class ConflictDetector:
    def detect_conflicts(self, entries: List[Dict]) -> List[Dict]:
        conflicts = []
        by_slot = defaultdict(list)

        for entry in entries:
            key = (entry['day_of_week'], entry['period'])
            by_slot[key].append(entry)

        for (day, period), slot_entries in by_slot.items():
            teacher_map = defaultdict(list)
            classroom_map = defaultdict(list)
            class_map = defaultdict(list)

            for entry in slot_entries:
                teacher_map[entry['teacher_id']].append(entry)
                classroom_map[entry['classroom_id']].append(entry)
                class_map[entry['class_id']].append(entry)

            for tid, t_entries in teacher_map.items():
                if len(t_entries) > 1:
                    conflicts.append({
                        'conflict_type': 'teacher',
                        'day_of_week': day,
                        'period': period,
                        'involved_entries': [e.get('id') for e in t_entries if e.get('id')],
                        'message': f"教师 {tid} 同一时间有 {len(t_entries)} 门课"
                    })

            for cid, c_entries in classroom_map.items():
                if len(c_entries) > 1:
                    conflicts.append({
                        'conflict_type': 'classroom',
                        'day_of_week': day,
                        'period': period,
                        'involved_entries': [e.get('id') for e in c_entries if e.get('id')],
                        'message': f"教室 {cid} 同一时间有 {len(c_entries)} 门课"
                    })

            for clid, cl_entries in class_map.items():
                if len(cl_entries) > 1:
                    conflicts.append({
                        'conflict_type': 'class',
                        'day_of_week': day,
                        'period': period,
                        'involved_entries': [e.get('id') for e in cl_entries if e.get('id')],
                        'message': f"班级 {clid} 同一时间有 {len(cl_entries)} 门课"
                    })

        return conflicts

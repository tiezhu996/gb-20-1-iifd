import random
import uuid
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass
from collections import defaultdict


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
class BlockWindow:
    """同一天上午/下午内一段连续的可排课空档。"""
    day: int
    start_period: int
    slots: List[TimeSlot]

    @property
    def end_period(self) -> int:
        return self.slots[-1].period

    @property
    def size(self) -> int:
        return len(self.slots)


class CSPScheduler:
    def __init__(self, semester):
        self.semester = semester
        self.weekly_days = semester.weekly_days
        self.daily_periods = len(semester.daily_periods) if semester.daily_periods else 7
        # 约定：每天前 4 节为上午，其余为下午，连堂课组不跨上午/下午
        self.morning_periods = min(4, self.daily_periods)
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

    # ---- 课组拆分 ----

    def build_block_sizes(self, task: SchedulingTask) -> List[int]:
        """把每周课时拆成若干完整连堂课组。

        例如每周 5 节、一次连排 2 节 -> [2, 2, 1]：
        前两组为完整连堂，余下 1 节单独成组，整组放置，不在空档里拆开。
        """
        block_size = max(1, task.consecutive_periods or 1)
        full_blocks, remainder = divmod(max(0, task.weekly_hours), block_size)
        sizes = [block_size] * full_blocks
        if remainder:
            sizes.append(remainder)
        return sizes

    # ---- 连续空档（上午/下午不混） ----

    def _segment_windows(self, size: int) -> Tuple[List[BlockWindow], List[BlockWindow]]:
        """枚举所有能容纳 size 节的连续窗口，按上午/下午分开返回。"""
        morning_windows: List[BlockWindow] = []
        afternoon_windows: List[BlockWindow] = []
        segments = [
            (1, self.morning_periods, morning_windows),
            (self.morning_periods + 1, self.daily_periods, afternoon_windows),
        ]
        for day in range(1, self.weekly_days + 1):
            for seg_start, seg_end, bucket in segments:
                for start in range(seg_start, seg_end - size + 2):
                    bucket.append(BlockWindow(
                        day=day,
                        start_period=start,
                        slots=[TimeSlot(day=day, period=p)
                               for p in range(start, start + size)]
                    ))
        return morning_windows, afternoon_windows

    def ordered_windows(
        self, size: int, priority: str
    ) -> List[BlockWindow]:
        """按优先级给出候选窗口顺序：主科倾向上午，副科倾向下午。"""
        morning, afternoon = self._segment_windows(size)
        morning.sort(key=lambda w: (w.day, w.start_period))
        afternoon.sort(key=lambda w: (w.day, w.start_period))

        if priority == 'high':
            return morning + afternoon
        if priority == 'low':
            return afternoon + morning
        all_windows = morning + afternoon
        return random.sample(all_windows, len(all_windows))

    # ---- 可用性检查 ----

    def is_slot_available(
        self,
        time_slot: TimeSlot,
        teacher_id: int,
        class_id: int,
        classroom_id: int,
        teacher_available_slots: Set[TimeSlot]
    ) -> bool:
        if teacher_available_slots and time_slot not in teacher_available_slots:
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
        window: BlockWindow,
        compatible_rooms: List[int],
        task: SchedulingTask,
        teacher_available: Set[TimeSlot]
    ) -> Optional[int]:
        """同班级、教师和教室连续占住：整段窗口须由同一间教室连续可用。"""
        for room in compatible_rooms:
            if all(
                self.is_slot_available(
                    slot, task.teacher_id, task.class_id, room, teacher_available
                )
                for slot in window.slots
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

    # ---- 放不下整组时的建议节次 ----

    def suggest_window(
        self,
        size: int,
        task: SchedulingTask,
        compatible_rooms: List[int],
        teacher_available: Set[TimeSlot]
    ) -> Optional[BlockWindow]:
        """在现有占用中找冲突最少的连续窗口，作为建议节次返回。"""
        morning, afternoon = self._segment_windows(size)
        if task.priority == 'low':
            ordered = afternoon + morning
        else:
            ordered = morning + afternoon
        if not ordered:
            return None

        def score(window: BlockWindow) -> Tuple[int, int, int]:
            value = 0
            for slot in window.slots:
                if slot not in self.class_usage[task.class_id]:
                    value += 1
                if slot not in self.teacher_usage[task.teacher_id]:
                    value += 1
                if teacher_available and slot not in teacher_available:
                    value -= 1
                value += sum(
                    1 for room in compatible_rooms
                    if slot not in self.classroom_usage[room]
                )
            return value, -window.day, -window.start_period

        return max(ordered, key=score)

    def _unplaced_message(
        self,
        task: SchedulingTask,
        block_size: int,
        compatible_rooms: List[int],
        teacher_available: Set[TimeSlot]
    ) -> Dict:
        suggestion = self.suggest_window(
            block_size, task, compatible_rooms, teacher_available
        )
        day_of_week = suggestion.day if suggestion else None
        suggested_periods = (
            [s.period for s in suggestion.slots] if suggestion else []
        )
        if suggestion:
            period_text = f"第{suggestion.start_period}-{suggestion.end_period}节"
            message = (
                f"课程《{task.course_name}》有 {block_size} 节连堂课组放不下完整空档"
                f"（未拆分），建议安排在星期{suggestion.day} {period_text}"
            )
        else:
            message = (
                f"课程《{task.course_name}》的 {block_size} 节连堂超过"
                f"上午/下午最大连续节数，无法成组安排"
            )
        return {
            'type': 'insufficient_slots',
            'course_id': task.course_id,
            'course_name': task.course_name,
            'class_id': task.class_id,
            'block_size': block_size,
            'day_of_week': day_of_week,
            'suggested_periods': suggested_periods,
            'message': message
        }

    # ---- 主排课流程 ----

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
            teacher_available = set()
            if teachers_data.get(task.teacher_id, {}).get('available_time_slots'):
                for slot_dict in teachers_data[task.teacher_id]['available_time_slots']:
                    teacher_available.add(
                        TimeSlot(day=slot_dict['day'], period=slot_dict['period'])
                    )

            compatible_rooms = self.get_compatible_classrooms(
                task.preferred_room_type,
                task.classroom_capacity,
                classrooms_data
            )

            if not compatible_rooms:
                self.conflicts.append({
                    'type': 'classroom',
                    'task': f"班级{task.class_id}的{task.course_id}",
                    'course_id': task.course_id,
                    'course_name': task.course_name,
                    'class_id': task.class_id,
                    'block_size': max(1, task.consecutive_periods or 1),
                    'day_of_week': None,
                    'suggested_periods': [],
                    'message': f"课程《{task.course_name}》没有找到容量满足"
                               f" {task.classroom_capacity} 人的 {task.preferred_room_type} 类型教室"
                })
                continue

            block_sizes = self.build_block_sizes(task)
            groups_placed = 0

            # 完整连堂优先排，余下小节组随后；整组放置，空档放不下时不拆开
            for block_size in block_sizes:
                placed_window = None
                placed_room = None
                for window in self.ordered_windows(block_size, task.priority):
                    room = self.find_room_for_window(
                        window, compatible_rooms, task, teacher_available
                    )
                    if room is not None:
                        placed_window = window
                        placed_room = room
                        break

                if placed_window is None:
                    self.conflicts.append(
                        self._unplaced_message(
                            task, block_size, compatible_rooms, teacher_available
                        )
                    )
                    continue

                block_id = uuid.uuid4()
                for slot in placed_window.slots:
                    self.classroom_usage[placed_room].add(slot)
                    self.teacher_usage[task.teacher_id].add(slot)
                    self.class_usage[task.class_id].add(slot)

                    self.assignments.append({
                        'semester_id': self.semester.id,
                        'class_id': task.class_id,
                        'course_id': task.course_id,
                        'teacher_id': task.teacher_id,
                        'classroom_id': placed_room,
                        'day_of_week': slot.day,
                        'period': slot.period,
                        'block_id': block_id,
                        'is_locked': False
                    })
                groups_placed += 1

            if groups_placed < len(block_sizes):
                unplaced = len(block_sizes) - groups_placed
                self.conflicts.append({
                    'type': 'placement_summary',
                    'course_id': task.course_id,
                    'course_name': task.course_name,
                    'class_id': task.class_id,
                    'day_of_week': None,
                    'suggested_periods': [],
                    'message': f"课程《{task.course_name}》共 {unplaced} 个连堂课组未能排入，"
                               f"详见上方建议节次"
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

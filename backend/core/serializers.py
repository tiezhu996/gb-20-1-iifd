from rest_framework import serializers
from .models import Classroom, Teacher, Class, Course, Semester


class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = '__all__'


class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = '__all__'


class ClassSerializer(serializers.ModelSerializer):
    class_teacher_name = serializers.CharField(source='class_teacher.name', read_only=True)

    class Meta:
        model = Class
        fields = '__all__'


class CourseSerializer(serializers.ModelSerializer):
    consecutive_periods = serializers.IntegerField(
        required=False, default=1, min_value=1, label='连排节数'
    )

    class Meta:
        model = Course
        fields = '__all__'

    def validate(self, data):
        weekly_hours = data.get('weekly_hours', getattr(self.instance, 'weekly_hours', None))
        consecutive_periods = data.get(
            'consecutive_periods',
            getattr(self.instance, 'consecutive_periods', 1)
        )
        if weekly_hours and consecutive_periods > weekly_hours:
            raise serializers.ValidationError({
                'consecutive_periods': '连排节数不能大于每周课时数'
            })
        return data

    def create(self, validated_data):
        validated_data.setdefault('consecutive_periods', 1)
        return super().create(validated_data)


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = '__all__'

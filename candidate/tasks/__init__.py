# Import all tasks here so Celery's autodiscover_tasks() can find them.
# autodiscover_tasks() looks for a 'tasks' module in each app.
# Since our tasks live in a sub-package, we explicitly import them here.

from candidate.tasks.process_cv import process_cv_task
from candidate.tasks.poll_ai_result import poll_ai_result_task
from candidate.tasks.generate_pdf import generate_enhanced_cv_pdf_task

__all__ = [
    "process_cv_task",
    "poll_ai_result_task",
    "generate_enhanced_cv_pdf_task",
]
FROM public.ecr.aws/lambda/python:3.12

COPY pyproject.toml ${LAMBDA_TASK_ROOT}/
COPY youtube_summary_notify/ ${LAMBDA_TASK_ROOT}/youtube_summary_notify/

RUN pip install --no-cache-dir "${LAMBDA_TASK_ROOT}"

CMD ["youtube_summary_notify.main.handler"]

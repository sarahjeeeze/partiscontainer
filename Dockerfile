FROM psathyrella/partis

RUN conda update numpy

RUN apt-get update

ENV APP_ROOT=/partis
ENV PATH="${APP_ROOT}:${PATH}"

COPY . /partis
WORKDIR /partis

CMD ./test/test.py --quick
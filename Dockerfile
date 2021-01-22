FROM psathyrella/partis

RUN conda update numpy

RUN apt-get update

RUN python -m pip install biopython==1.76

ENV APP_ROOT=/partis
ENV PATH="${APP_ROOT}:${PATH}"

COPY . /partis
WORKDIR /partis

CMD ./test/test.py --quick
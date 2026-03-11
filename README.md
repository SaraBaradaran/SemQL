# SemQL
An extension of CodeQL language

## Download and Install CodeQL
```
wget https://github.com/github/codeql-action/releases/download/codeql-bundle-v2.17.0/codeql-bundle-linux64.tar.gz
tar -xzf codeql-bundle-linux64.tar.gz 
export PATH=$PATH:/path/to/codeql
codeql resolve qlpacks
```

to run the benchmakrs on the SpotBugs code base, you simply need to do the following steps
#### Clone the Codebase
```
git clone https://github.com/spotbugs/spotbugs
```
#### Create The Dataset of Facts
```
codeql database create example-database --language=java --source-root=spotbugs/spotbugsTestCases/src/java --build-mode=none
```
#### Run A SemQL Benchmakr Query

```
python3 SemQL.py query run ./SemQL/benchmarks/NM_TRUSTWORTHY_URL.ql --database=example-database --output=tmp.bqrs
```


